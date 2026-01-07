terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# 1. Dynamic AMI Lookup (Canonical Ubuntu 22.04 LTS)
data "aws_ami" "ubuntu" {
  most_recent = true

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  owners = ["099720109477"] # Canonical
}

# 2. Security Group: Allow SSH
resource "aws_security_group" "benchmark_sg" {
  name        = "benchmark_sg"
  description = "Allow SSH inbound traffic"

  ingress {
    description = "SSH from anywhere"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"] 
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# 3. Key Pair
resource "aws_key_pair" "deployer" {
  key_name   = "benchmark-key"
  public_key = file(var.public_key_path)
}

# 4. EC2 Instance
resource "aws_instance" "remote_lab" {
  ami           = data.aws_ami.ubuntu.id
  instance_type = var.instance_type
  key_name      = aws_key_pair.deployer.key_name

  vpc_security_group_ids = [aws_security_group.benchmark_sg.id]

  root_block_device {
    volume_size = 30 # GB
    volume_type = "gp3"
  }

  tags = {
    Name        = "SQL-Benchmarks-Remote-Lab"
    Environment = "Benchmarking"
    Project     = "Dagster-SQL-Benchmarks"
  }
}
