variable "aws_region" {
  type        = string
  description = "AWS region for the public research demo."
  default     = "eu-west-2"
}

variable "environment" {
  type        = string
  description = "Deployment environment name."
  default     = "demo"
}

variable "document_bucket_name" {
  type        = string
  description = "Globally unique S3 bucket name used for encrypted research documents."
}

variable "instance_type" {
  type        = string
  description = "EC2 size for the single-node k3s demo cluster and local LLM."
  default     = "t3.xlarge"
}

variable "admin_cidr" {
  type        = string
  description = "CIDR allowed to SSH to the demo instance."
}

variable "key_name" {
  type        = string
  description = "Existing EC2 key pair name."
}
