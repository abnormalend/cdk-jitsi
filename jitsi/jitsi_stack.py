from aws_cdk import (
    # Duration,
    Stack,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_route53 as dns,
    Tags
    # aws_sqs as sqs,
)
import os
from constructs import Construct
from aws_cdk.aws_s3_assets import Asset
from aws_cdk import CfnParameter
from aws_cdk import Token
dirname = os.path.dirname(__file__)

class JitsiStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        dns_host_name = os.environ.get('JITSI_HOSTNAME', 'meet')
        long_lived = os.environ.get('JITSI_LONGLIVED', False)
        jitsi_instance_type = os.environ.get('JITSI_INSTANCETYPE', 't3a.small')
        try:
            jitsi_email = os.environ["JITSI_EMAIL"]
            dns_zone_name = os.environ.get('JITSI_ZONENAME')
        except KeyError as e:
            print("Tried accessing an environment variable that does not exist")
            exit(1)
        vpc = ec2.Vpc.from_lookup(self, "VPC", is_default=True)

        ubuntu_linux = ec2.MachineImage.from_ssm_parameter('/aws/service/canonical/ubuntu/server/focal/stable/current/amd64/hvm/ebs-gp2/ami-id',
                                                           os = ec2.OperatingSystemType.LINUX,)

        jitsi_security = ec2.SecurityGroup(self, "Jitsi Security", vpc = vpc)
        jitsi_security.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(443), 'Allow Jitsi from Anywhere')
        jitsi_security.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(80), 'Allow Jitsi from Anywhere')
        jitsi_security.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(4443), 'Allow Jitsi from Anywhere')
        jitsi_security.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.udp(10000), 'Allow Jitsi from Anywhere')
        if long_lived:
            jitsi_security.add_ingress_rule(ec2.Peer.ipv4('3.16.146.0/29'), ec2.Port.tcp(22), 'Allow SSH From EC2 Instance Connect')

        role = iam.Role(self, "InstancePermissions", assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"))
        role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore"))
        role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("CloudWatchAgentServerPolicy"))

        # Create an EC2 Instance for our jitsi server based on the things we've already done above.
        jitsi_server =  ec2.Instance(self, "Jitsi Server",
                            instance_type=ec2.InstanceType(jitsi_instance_type),
                            machine_image=ubuntu_linux,
                            vpc = vpc,
                            role = role,
                            security_group = jitsi_security
                            )

        jitsi_user_data = ec2.MultipartUserData()

        jitsi_dns_updater = """
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
        """

        jitsi_user_data = """
#!/bin/sh
echo 'deb https://download.jitsi.org stable/' >> /etc/apt/sources.list.d/jitsi-stable.list
wget -qO - https://download.jitsi.org/jitsi-key.gpg.key | apt-key add -
apt-get update
echo "DefaultLimitNOFILE=65000" >> /etc/systemd/system.conf
echo "DefaultLimitNPROC=65000" >> /etc/systemd/system.conf
echo "DefaultTasksMax=65000" >> /etc/systemd/system.conf
systemctl daemon-reload

echo 'jitsi-videobridge jitsi-videobridge/jvb-hostname string meet.minecloud.xyz' | debconf-set-selections
echo 'jitsi-meet jitsi-meet/cert-choice select Self-signed certificate will be generated' | debconf-set-selections
export DEBIAN_FRONTEND=noninteractive
apt -y install jitsi-meet

echo {} | /usr/share/jitsi-meet/scripts/install-letsencrypt-cert.sh

systemctl enable jitsi-videobridge2
service jitsi-videobridge2 start
        """.format(jitsi_email)


        jitsi_server.add_user_data(jitsi_user_data)

        Tags.of(jitsi_server).add("dns_hostname", dns_host_name)
        Tags.of(jitsi_server).add("dns_zone_name", dns_zone_name)
        # We build out an ARN of the server so that we can plug it into the policy below
        # jitsi_server_arn = Stack.of(self).format_arn(service="ec2", resource="instance", resource_name= jitsi_server.instance_id )

        # This role allows this server to get the details of other instances, and change anything on itself.  This is used to read/update it's own tags
        # role.attach_inline_policy(iam.Policy(self, "EC2 self access", statements = [iam.PolicyStatement(effect=iam.Effect.ALLOW,
        #                                         resources=[jitsi_server_arn],
        #                                         actions=["ec2:*"]),
        #                                         iam.PolicyStatement(effect=iam.Effect.ALLOW,
        #                                         resources=["*"],
        #                                         actions=["ec2:Describe*"])]))

        # role.attach_inline_policy(iam.Policy(self, "DNS Updating Access", statements = [iam.PolicyStatement(effect=iam.Effect.ALLOW,
        #                                         resources=[jitsi_server_arn],
        #                                         actions=["ec2:*"]),
        #                                         iam.PolicyStatement(effect=iam.Effect.ALLOW,
        #                                         resources=["arn:aws:route53:::hostedzone/" + dns_zone.hosted_zone_id],
        #                                         actions=["route53:ChangeResourceRecordSets"]),
        #                                         iam.PolicyStatement(effect=iam.Effect.ALLOW,
        #                                         resources=["*"],
        #                                         actions=["route53:ListHostedZones"])
        #                                         ]))

        dns_zone = dns.HostedZone.from_lookup(self, "DNS Zone", domain_name = dns_zone_name)
        dns_setup = dns.ARecord(self, "jitsi dns",
                        zone=dns_zone,
                        record_name="{}.{}".format(dns_host_name, dns_zone_name),
                        target=dns.RecordTarget.from_ip_addresses(jitsi_server.instance_public_ip))
