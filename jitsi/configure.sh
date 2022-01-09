#!/bin/sh

# Set up DNS
tee /opt/dns_updater.py << EOF
#!/usr/bin/python3
import boto3
import requests


instance = requests.get("http://169.254.169.254/latest/meta-data/instance-id").text
ec2 = boto3.resource('ec2', region_name='us-east-1')
myinstance = ec2.Instance(instance)

# Look up the Hostname tag
try:
    myMachine = next(t["Value"] for t in instance.tags if t["Key"] == "dns_hostname")
except StopIteration:
    print("Unable to locate tag 'dns_hostname', cannot continue")
    exit(1)
    
# Look up the Hosted Zone tag
try:
    myZone = next(t["Value"] for t in instance.tags if t["Key"] == "dns_zone")
except StopIteration:
    print("Unable to locate tag 'dns_zone', cannot continue")
    exit(1)

myCurrIP = requests.get("http://169.254.169.254/latest/meta-data/public-ipv4").text

# Make a connection to Route53 to update the record
conn53 = boto3.client('route53')
myzone = conn53.list_hosted_zones()

try:
    myzoneid = next(z["Id"] for z in myzone['HostedZones'] if z["Name"] == myZone)
except StopIteration:
    print("Unable to find hosted zone in route53, unable to update DNS")
    exit(1)

response = conn53.change_resource_record_sets(
    HostedZoneId=myzoneid,
    ChangeBatch={
        "Comment": "Automatic DNS update",
        "Changes": [
            {
                "Action": "UPSERT",
                "ResourceRecordSet": {
                    "Name": myMachine + "." + myZone,
                    "Type": "A",
                    "TTL": 180,
                    "ResourceRecords": [
                        {
                            "Value": myCurrIP
                        },
                    ],
                }
            },
        ]
    }
)

print("DNSLOG: " + myMachine + "." + myZone + " updated to " + myCurrIP)
EOF
chmod +x dns_updater.py
echo "@reboot root /opt/dns_updater.py" /etc/cron.d/dnsupdater
/opt/dns_updater.py

echo 'deb https://download.jitsi.org stable/' >> /etc/apt/sources.list.d/jitsi-stable.list
wget -qO - https://download.jitsi.org/jitsi-key.gpg.key | apt-key add -
apt-get update
echo "DefaultLimitNOFILE=65000" >> /etc/systemd/system.conf
echo "DefaultLimitNPROC=65000" >> /etc/systemd/system.conf
echo "DefaultTasksMax=65000" >> /etc/systemd/system.conf
systemctl daemon-reload

echo “jitsi-videobridge jitsi-videobridge/jvb-hostname string meet.minecloud.xyz” | debconf-set-selections
echo “jitsi-meet jitsi-meet/cert-choice select Self-signed certificate will be generated” | debconf-set-selections
export DEBIAN_FRONTEND=noninteractive
apt -y install jitsi-meet

echo “brentarogers@gmail.com” | /usr/share/jitsi-meet/scripts/install-letsencrypt-cert.sh

systemctl enable jitsi-videobridge2
service jitsi-videobridge2 start