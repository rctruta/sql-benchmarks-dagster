import boto3
import sys

def check_instance_viability():
    # Setup AWS client
    # This will use the credentials from ~/.aws/credentials which the user already set up
    ec2 = boto3.client('ec2', region_name='us-east-1')

    print("--- DIAGNOSTIC: Checking t2.micro availability ---")
    
    try:
        # 1. Describe Offerings to find valid AZs for t2.micro
        response = ec2.describe_instance_type_offerings(
            LocationType='availability-zone',
            Filters=[{'Name': 'instance-type', 'Values': ['t2.micro']}]
        )
        
        valid_azs = [o['Location'] for o in response['InstanceTypeOfferings']]
        print(f"Valid AZs for t2.micro: {valid_azs}")
        
        if not valid_azs:
            print("CRITICAL: t2.micro is NOT available in this region/account.")
            return False

        # 2. Check current default subnets
        subnets = ec2.describe_subnets(Filters=[{'Name': 'default-for-az', 'Values': ['true']}])
        print(f"Default Subnets Found: {len(subnets['Subnets'])}")
        
        for s in subnets['Subnets']:
            print(f" - Subnet {s['SubnetId']} in {s['AvailabilityZone']}")
            
        print("--------------------------------------------------")
        return True

    except Exception as e:
        print(f"AWS Error: {e}")
        return False

if __name__ == "__main__":
    check_instance_viability()
