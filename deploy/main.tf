# ═══════════════════════════════════════════════════════════
# Pagemenot — Multi-cloud Terraform
#
# Deploy Pagemenot to ANY provider with one command:
#   terraform init
#   terraform apply -var="provider=aws"      # or gcp, hetzner, digitalocean
#
# All providers run the same Docker image.
# ═══════════════════════════════════════════════════════════

variable "provider_choice" {
  description = "Cloud provider: aws, gcp, hetzner, digitalocean"
  type        = string
  default     = "hetzner"
}

variable "ssh_key_name" {
  description = "Name of your SSH key (pre-configured in the provider)"
  type        = string
}

variable "region" {
  description = "Region to deploy to (provider-specific)"
  type        = string
  default     = ""
}

locals {
  default_regions = {
    aws           = "us-east-1"
    gcp           = "us-central1-a"
    hetzner       = "nbg1"
    digitalocean  = "nyc1"
  }
  region = var.region != "" ? var.region : local.default_regions[var.provider_choice]

  user_data = file("${path.module}/generic-userdata.sh")
}

# ══════════════════════════════════════════════════════════
# AWS
# ══════════════════════════════════════════════════════════

provider "aws" {
  region = local.region
}

resource "aws_instance" "pagemenot" {
  count = var.provider_choice == "aws" ? 1 : 0

  ami           = "ami-0c02fb55956c7d316" # Amazon Linux 2023
  instance_type = "t3.micro"              # Free tier eligible
  key_name      = var.ssh_key_name
  user_data     = local.user_data

  root_block_device {
    volume_size           = 20
    delete_on_termination = true
  }

  tags = {
    Name = "pagemenot"
  }
}

# ══════════════════════════════════════════════════════════
# GCP
# ══════════════════════════════════════════════════════════

provider "google" {
  project = "your-project-id"
  region  = local.region
}

resource "google_compute_instance" "pagemenot" {
  count = var.provider_choice == "gcp" ? 1 : 0

  name         = "pagemenot"
  machine_type = "e2-micro"  # Always-free tier
  zone         = local.region

  boot_disk {
    initialize_params {
      image = "ubuntu-os-cloud/ubuntu-2404-lts"
      size  = 20
    }
  }

  network_interface {
    network = "default"
    access_config {} # Public IP
  }

  metadata_startup_script = local.user_data
}

# ══════════════════════════════════════════════════════════
# Hetzner
# ══════════════════════════════════════════════════════════

provider "hcloud" {
  # HCLOUD_TOKEN env var
}

resource "hcloud_server" "pagemenot" {
  count = var.provider_choice == "hetzner" ? 1 : 0

  name        = "pagemenot"
  server_type = "cx22"        # 2 vCPU, 4GB, €3.99/mo
  image       = "ubuntu-24.04"
  location    = local.region
  user_data   = local.user_data

  ssh_keys = [var.ssh_key_name]
}

# ══════════════════════════════════════════════════════════
# DigitalOcean
# ══════════════════════════════════════════════════════════

provider "digitalocean" {
  # DIGITALOCEAN_TOKEN env var
}

resource "digitalocean_droplet" "pagemenot" {
  count = var.provider_choice == "digitalocean" ? 1 : 0

  name     = "pagemenot"
  size     = "s-1vcpu-1gb"   # $6/mo
  image    = "ubuntu-24-04-x64"
  region   = local.region
  ssh_keys = [var.ssh_key_name]

  user_data = local.user_data
}

# ══════════════════════════════════════════════════════════
# Outputs
# ══════════════════════════════════════════════════════════

output "server_ip" {
  value = coalesce(
    try(aws_instance.pagemenot[0].public_ip, ""),
    try(google_compute_instance.pagemenot[0].network_interface[0].access_config[0].nat_ip, ""),
    try(hcloud_server.pagemenot[0].ipv4_address, ""),
    try(digitalocean_droplet.pagemenot[0].ipv4_address, ""),
  )
}

output "ssh_command" {
  value = "ssh root@${coalesce(
    try(aws_instance.pagemenot[0].public_ip, ""),
    try(google_compute_instance.pagemenot[0].network_interface[0].access_config[0].nat_ip, ""),
    try(hcloud_server.pagemenot[0].ipv4_address, ""),
    try(digitalocean_droplet.pagemenot[0].ipv4_address, ""),
  )}"
}

output "health_check" {
  value = "curl http://${coalesce(
    try(aws_instance.pagemenot[0].public_ip, ""),
    try(google_compute_instance.pagemenot[0].network_interface[0].access_config[0].nat_ip, ""),
    try(hcloud_server.pagemenot[0].ipv4_address, ""),
    try(digitalocean_droplet.pagemenot[0].ipv4_address, ""),
  )}:8080/health"
}
