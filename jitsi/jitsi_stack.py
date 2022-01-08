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

dirname = os.path.dirname(__file__)

class JitsiStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        vpc = ec2.Vpc.from_lookup(self, "VPC", is_default=True)

        # Find the latest Amazon Linux 2 AMI to use for our image
        # amzn_linux = ec2.MachineImage.latest_amazon_linux(
        #                 generation=ec2.AmazonLinuxGeneration.AMAZON_LINUX_2,
        #                 edition=ec2.AmazonLinuxEdition.STANDARD,
        #                 virtualization=ec2.AmazonLinuxVirt.HVM,
        #                 storage=ec2.AmazonLinuxStorage.GENERAL_PURPOSE )


        ubuntu_linux = ec2.MachineImage.from_ssm_parameter('/aws/service/canonical/ubuntu/server/focal/stable/current/amd64/hvm/ebs-gp2/ami-id',
                                                           os = ec2.OperatingSystemType.LINUX,)

        jitsi_security = ec2.SecurityGroup(self, "Jitsi Security", vpc = vpc)
        jitsi_security.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(443), 'Allow Jitsi from Anywhere')
        jitsi_security.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(80), 'Allow Jitsi from Anywhere')
        jitsi_security.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(4443), 'Allow Jitsi from Anywhere')
        jitsi_security.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.udp(10000), 'Allow Jitsi from Anywhere')
        jitsi_security.add_ingress_rule(ec2.Peer.ipv4('3.16.146.0/29'), ec2.Port.tcp(22), 'Allow SSH From EC2 Instance Connect')

        role = iam.Role(self, "InstancePermissions", assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"))
        role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore"))
        role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("CloudWatchAgentServerPolicy"))

        # Create an EC2 Instance for our jitsi server based on the things we've already done above.
        jitsi_server =  ec2.Instance(self, "Jitsi Server",
                            instance_type=ec2.InstanceType(self.node.try_get_context("InstanceType")),
                            machine_image=ubuntu_linux,
                            vpc = vpc,
                            role = role,
                            key_name  = self.node.try_get_context("sshKeyName"),
                            security_group = jitsi_security
                            )

        jitsi_user_data = ec2.MultipartUserData()
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

echo brentarogers@gmail.com | /usr/share/jitsi-meet/scripts/install-letsencrypt-cert.sh

systemctl enable jitsi-videobridge2
service jitsi-videobridge2 start
        """


        jitsi_server.add_user_data(jitsi_user_data)

        # There is a section for tags in cdk.json.  We're going to add all those tags to the server we just created.
        for key, value in self.node.try_get_context("tags").items():
            Tags.of(jitsi_server).add(key, value)

        # We build out an ARN of the server so that we can plug it into the policy below
        jitsi_server_arn = Stack.of(self).format_arn(service="ec2", resource="instance", resource_name= jitsi_server.instance_id )

        # This role allows this server to get the details of other instances, and change anything on itself.  This is used to read/update it's own tags
        role.attach_inline_policy(iam.Policy(self, "EC2 self access", statements = [iam.PolicyStatement(effect=iam.Effect.ALLOW,
                                                resources=[jitsi_server_arn],
                                                actions=["ec2:*"]),
                                                iam.PolicyStatement(effect=iam.Effect.ALLOW,
                                                resources=["*"],
                                                actions=["ec2:Describe*"])]))

        # asset = Asset(self, "Asset", path=os.path.join(dirname, "configure.sh"))
        # local_path = jitsi_server.user_data.add_s3_download_command(
        #     bucket=asset.bucket,
        #     bucket_key=asset.s3_object_key)

        dns_zone = dns.HostedZone.from_lookup(self, "DNS Zone", domain_name = self.node.try_get_context("tags")['dns_zone'] )

        role.attach_inline_policy(iam.Policy(self, "DNS Updating Access", statements = [iam.PolicyStatement(effect=iam.Effect.ALLOW,
                                                resources=[jitsi_server_arn],
                                                actions=["ec2:*"]),
                                                iam.PolicyStatement(effect=iam.Effect.ALLOW,
                                                resources=["arn:aws:route53:::hostedzone/" + dns_zone.hosted_zone_id],
                                                actions=["route53:ChangeResourceRecordSets"]),
                                                iam.PolicyStatement(effect=iam.Effect.ALLOW,
                                                resources=["*"],
                                                actions=["route53:ListHostedZones"])
                                                ]))

        dns_setup = dns.ARecord(self, "jitsi dns",
                        zone=dns_zone,
                        record_name="{}.{}".format(self.node.try_get_context("tags")['dns_hostname'], self.node.try_get_context("tags")['dns_zone']),
                        target=dns.RecordTarget.from_ip_addresses(jitsi_server.instance_public_ip))
