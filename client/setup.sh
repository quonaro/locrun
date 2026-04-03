#!/bin/bash

# LocRun Client Initialization Script
# Interactive setup script for LocRun client

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
DEFAULT_DOMAIN="example.com"
CONFIG_FILE="$HOME/.locrun_config"

# Functions
print_header() {
    echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║         LocRun Client Setup            ║${NC}"
    echo -e "${BLUE}║     Self-Hosted Tunneling Client       ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
    echo
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

check_domain_availability() {
    local domain="$1"
    print_info "Checking domain availability: $domain"
    
    # Check DNS resolution
    if ! host "$domain" >/dev/null 2>&1; then
        print_error "Domain $domain does not resolve in DNS"
        return 1
    fi
    
    # Check SSH connectivity
    if ! timeout 10 nc -zv "$domain" 22 2>/dev/null; then
        print_error "Port 22 (SSH) is not available on $domain"
        return 1
    fi
    
    # Try SSH connection test (without actually connecting)
    if timeout 10 ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no tun@"$domain" 'echo "SSH_OK"' 2>/dev/null | grep -q "SSH_OK"; then
        print_success "SSH is available on $domain"
        return 0
    else
        print_warning "SSH test failed, but domain is reachable"
        print_info "Make sure SSH key is properly configured"
        return 0
    fi
}

validate_port() {
    local port="$1"
    if ! [[ "$port" =~ ^[0-9]+$ ]]; then
        print_error "Port must be a number"
        return 1
    fi
    
    if [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
        print_error "Port must be in range 1-65535"
        return 1
    fi
    
    if [ "$port" -lt 1024 ]; then
        print_warning "Port $port is privileged, root privileges may be required"
    fi
    
    return 0
}

create_alias() {
    local domain="$1"
    local shell_config=""
    
    # Detect shell
    if [ -n "$ZSH_VERSION" ]; then
        shell_config="$HOME/.zshrc"
    elif [ -n "$BASH_VERSION" ]; then
        shell_config="$HOME/.bashrc"
    else
        print_warning "Could not detect shell, using ~/.zshrc"
        shell_config="$HOME/.zshrc"
    fi
    
    print_info "Creating alias in $shell_config"
    
    # Backup existing config
    if [ -f "$shell_config" ]; then
        cp "$shell_config" "$shell_config.locrun.backup.$(date +%Y%m%d_%H%M%S)"
        print_info "Created backup: $shell_config.locrun.backup.$(date +%Y%m%d_%H%M%S)"
    fi
    
    # Remove existing locrun alias
    if grep -q "locrun()" "$shell_config" 2>/dev/null; then
        print_info "Removing existing locrun alias"
        sed -i '/^locrun()/,/^}$/d' "$shell_config"
    fi
    
    # Add new alias
    cat >> "$shell_config" << 'EOF'

# LocRun Tunnel Alias
locrun() {
    # Load config
    local config_file="$HOME/.locrun_config"
    if [ -f "$config_file" ]; then
        source "$config_file"
    else
        echo "❌ Error: Configuration not found. Run initialization script again."
        return 1
    fi
    
    # Check if port argument is provided
    if [ -z "$1" ]; then
        echo "❌ Error: Please specify a port!"
        echo "Example: locrun 25313"
        echo "Current server: $LOCRUN_DOMAIN"
        return 1
    fi

    local port=$1
    
    # Port validation
    if ! [[ "$port" =~ ^[0-9]+$ ]]; then
        echo "❌ Error: Port must be a number"
        return 1
    fi
    
    if [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
        echo "❌ Error: Port must be in range 1-65535"
        return 1
    fi

    echo "🚀 Creating tunnel: $LOCRUN_DOMAIN -> localhost:$port"
    echo "📝 Tunnel domain will be: https://<random>.tun.$LOCRUN_DOMAIN"
    echo

    # -C: compression
    # -R: reverse port forwarding
    # -o ServerAliveInterval=60: keep connection alive
    # 127.0.0.1: avoid IPv6 issues
    ssh -C -R 0:127.0.0.1:$port -o ServerAliveInterval=60 tun@$LOCRUN_DOMAIN
}
EOF

    print_success "Alias created in $shell_config"
}

save_config() {
    local domain="$1"
    cat > "$CONFIG_FILE" << EOF
# LocRun Client Configuration
LOCRUN_DOMAIN="$domain"
LOCRUN_CONFIG_DATE="$(date)"
EOF
    print_success "Configuration saved to $CONFIG_FILE"
}

# Main script
main() {
    print_header
    
    print_info "This script will configure LocRun client for tunnel creation"
    echo
    
    # Check if config exists
    if [ -f "$CONFIG_FILE" ]; then
        print_warning "Found existing configuration:"
        cat "$CONFIG_FILE"
        echo
        read -p "Do you want to recreate configuration? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_info "Using existing configuration"
            source "$CONFIG_FILE"
            create_alias "$LOCRUN_DOMAIN"
            print_success "Setup complete! Restart terminal or run 'source $shell_config'"
            return 0
        fi
    fi
    
    # Domain input
    echo
    print_info "Enter LocRun server domain:"
    echo "Example: example.com"
    echo
    read -p "Domain [$DEFAULT_DOMAIN]: " user_domain
    
    # Set domain (use default if empty)
    if [ -z "$user_domain" ]; then
        domain="$DEFAULT_DOMAIN"
    else
        domain="$user_domain"
    fi
    
    echo
    print_info "Using domain: $domain"
    echo
    
    # Check domain availability
    if ! check_domain_availability "$domain"; then
        print_error "Domain $domain is not available!"
        echo
        read -p "Continue anyway? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_info "Exiting script"
            exit 1
        fi
    fi
    
    # Save config
    save_config "$domain"
    
    # Create alias
    create_alias "$domain"
    
    echo
    print_success "Setup completed! 🎉"
    echo
    print_info "What to do next:"
    echo "1. Restart terminal OR run: source ~/.zshrc (or ~/.bashrc)"
    echo "2. Use command: locrun <port>"
    echo "   Example: locrun 25313"
    echo
    print_info "Configuration file: $CONFIG_FILE"
    print_info "To change domain, remove config file and run script again"
    echo
}

# Run main function
main "$@"
