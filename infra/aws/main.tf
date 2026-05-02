# AskAi on AWS — EKS + RDS Postgres (pgvector) + S3 + ElastiCache.
# Pairs with the Helm chart in infra/helm/.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.70" }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  type    = string
  default = "eu-west-2"
}

variable "prefix" {
  type    = string
  default = "askai"
}

variable "env" {
  type    = string
  default = "dev"
}

# ---- VPC + EKS (kept minimal — production use modules/eks) ---------------

data "aws_availability_zones" "available" {}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.13"
  name    = "${var.prefix}-${var.env}-vpc"
  cidr    = "10.20.0.0/16"
  azs             = slice(data.aws_availability_zones.available.names, 0, 3)
  private_subnets = ["10.20.1.0/24", "10.20.2.0/24", "10.20.3.0/24"]
  public_subnets  = ["10.20.101.0/24", "10.20.102.0/24", "10.20.103.0/24"]
  enable_nat_gateway = true
  single_nat_gateway = true
}

module "eks" {
  source          = "terraform-aws-modules/eks/aws"
  version         = "~> 20.24"
  cluster_name    = "${var.prefix}-${var.env}"
  cluster_version = "1.30"
  vpc_id          = module.vpc.vpc_id
  subnet_ids      = module.vpc.private_subnets
  eks_managed_node_groups = {
    default = {
      desired_size   = var.env == "prod" ? 3 : 2
      min_size       = 2
      max_size       = 6
      instance_types = ["m6i.large"]
    }
  }
}

# ---- RDS Postgres with pgvector ------------------------------------------

resource "aws_db_subnet_group" "askai" {
  name       = "${var.prefix}-${var.env}-pg"
  subnet_ids = module.vpc.private_subnets
}

resource "aws_security_group" "pg" {
  name        = "${var.prefix}-${var.env}-pg-sg"
  vpc_id      = module.vpc.vpc_id
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [module.eks.cluster_primary_security_group_id]
  }
}

resource "aws_db_parameter_group" "pgvector" {
  name   = "${var.prefix}-${var.env}-pgvector"
  family = "postgres16"
  parameter {
    name  = "shared_preload_libraries"
    value = "vector"
    apply_method = "pending-reboot"
  }
}

resource "aws_db_instance" "askai" {
  identifier             = "${var.prefix}-${var.env}"
  engine                 = "postgres"
  engine_version         = "16.4"
  instance_class         = var.env == "prod" ? "db.m6g.large" : "db.t4g.medium"
  allocated_storage      = 50
  username               = "askai"
  password               = "PLEASE-OVERRIDE"
  db_subnet_group_name   = aws_db_subnet_group.askai.name
  vpc_security_group_ids = [aws_security_group.pg.id]
  parameter_group_name   = aws_db_parameter_group.pgvector.name
  skip_final_snapshot    = true
}

# ---- S3 ------------------------------------------------------------------

resource "aws_s3_bucket" "askai" {
  bucket = "${var.prefix}-${var.env}-storage"
}

resource "aws_s3_bucket_public_access_block" "askai" {
  bucket                  = aws_s3_bucket.askai.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ---- ElastiCache Redis ---------------------------------------------------

resource "aws_elasticache_subnet_group" "askai" {
  name       = "${var.prefix}-${var.env}-redis"
  subnet_ids = module.vpc.private_subnets
}

resource "aws_elasticache_replication_group" "askai" {
  replication_group_id  = "${var.prefix}-${var.env}-redis"
  description           = "AskAi Redis"
  engine                = "redis"
  node_type             = "cache.t4g.small"
  num_cache_clusters    = 1
  port                  = 6379
  subnet_group_name     = aws_elasticache_subnet_group.askai.name
  automatic_failover_enabled = false
}

output "eks_cluster_name" { value = module.eks.cluster_name }
output "rds_endpoint"     { value = aws_db_instance.askai.endpoint }
output "s3_bucket"        { value = aws_s3_bucket.askai.id }
output "redis_endpoint"   { value = aws_elasticache_replication_group.askai.primary_endpoint_address }
