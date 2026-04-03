locrun() {
    # Check if port argument is provided
    if [ -z "$1" ]; then
        echo "❌ Error: Please specify a port!"
        echo "Example: locrun 25313"
        return 1
    fi

    local port=$1

    echo "🚀 Creating tunnel: example.com -> localhost:$port"

    # -C: compression
    # -R: reverse port forwarding
    # 127.0.0.1: avoid IPv6 issues
    ssh -C -R 0:127.0.0.1:$port appuser@example.com
}
