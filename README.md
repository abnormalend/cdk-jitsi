
# CDK-Jitsi

## What is Jitsi?

Jitsi is a set of open-source projects that allows you to easily build and deploy secure video conferencing solutions. At the heart of Jitsi are Jitsi Videobridge and Jitsi Meet, which let you have conferences on the internet, while other projects in the community enable other features such as audio, dial-in, recording, and simulcasting.

https://jitsi.org/

## What is CDK-Jitsi?

CDK-Jitsi is a quick way to deploy your own Jitsi server in AWS.  You can use this as a replacement for Zoom, Microsoft Teams, etc.

The default options will create a short lived jitsi server that you can just delete when you're done with it.  Alternatively, if you set the long-lived option, it will create one that you can power down when you don't need it, and just turn it back on when you do.

## CDK-Jitsi creates

- An EC2 instance inside your default VPC
  - Latest Ubuntu AMI
  - apt upgrade done during creation
  - jitsi-videobridge2 installed and set to run on boot
  - TLS Certificate generated via letsencrypt for the FQDN specified during setup.
- Role policies for the EC2 server
- DNS A Record in AWS Route53 that points to the public IP of the instance
- Optionally, if choosing long-lived:
  - A Python script to update DNS on boot
  - Additional role policies to allow script to function.

## Requirements

- An AWS Account.
- IAM Access keys set up to use the AWS account
- Something with the AWS CLI, and CDK 2.4 or newer (cloud9 would probably work)

## Environment Variables

The following must be defined for your installation...

- CDK_DEFAULT_ACCOUNT
  - your AWS account number, example: 123456789012
- CDK_DEFAULT_REGION
  - the region you wish to install Jitsi into, example: us-west-2
- JITSI_EMAIL
  - email address to be used for letsencrypt.  Certificate notifications will be sent there.
- JITSI_ZONENAME
  - the name of the DNS zone in AWS Route53 that we will be putting an A record into.
- JITSI_HOSTNAME
  - the hostname of the server, combines with ZONENAME to be the FQDN.
  - default: meet
- JITSI_INSTANCETYPE
  - What type of EC2 instance to deploy Jitsi on.
  - default: t3a.small
- JITSI_LONGLIVED
  - Sets up additional things like:
    - Terminal access via EC2 instance connect
    - Python script to update DNS record on boot
    - Role permissions to allow server to update Route53 records
  - default: false
