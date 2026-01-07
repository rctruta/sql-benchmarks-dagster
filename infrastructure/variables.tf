variable "aws_region" {
  description = "AWS Region to deploy to"
  type        = string
  default     = "us-east-1"
}

variable "instance_type" {
  description = "EC2 Instance Type"
  type        = string
  default     = "t3.medium"
}

variable "ami_id" {
  description = "AMI ID for Ubuntu 22.04 LTS (us-east-1)"
  type        = string
  default     = "ami-0c7217cdde317cfec" 
}

variable "public_key_path" {
  description = "Path to your local public SSH key"
  type        = string
}