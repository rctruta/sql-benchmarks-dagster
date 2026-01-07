output "remote_lab_ip" {
  description = "The public IP address of the Remote Lab instance"
  value       = aws_instance.remote_lab.public_ip
}

output "ssh_command" {
  description = "Command to connect to the instance"
  value       = "ssh ubuntu@${aws_instance.remote_lab.public_ip}"
}
