output "public_ip" {
  value = aws_eip.research.public_ip
}

output "document_bucket" {
  value = aws_s3_bucket.documents.bucket
}

output "api_ecr_repository" {
  value = aws_ecr_repository.api.repository_url
}

output "web_ecr_repository" {
  value = aws_ecr_repository.web.repository_url
}

output "cloudwatch_log_group" {
  value = aws_cloudwatch_log_group.research.name
}
