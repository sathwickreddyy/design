#!/bin/bash
# =============================================
# Test Script for Sticky Sessions Demo
# =============================================

echo "🧪 Testing Sticky Sessions with ip_hash"
echo "========================================"
echo ""
echo "Making 10 requests to http://localhost:8080"
echo "With ip_hash enabled, ALL requests should go to the SAME server"
echo ""

for i in {1..10}; do
    response=$(curl -s http://localhost:8080 | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Request {$i}: {d[\"app_name\"]} (PID: {d[\"process_id\"]})')" 2>/dev/null)
    echo "$response"
    sleep 0.2
done

echo ""
echo "========================================"
echo "✅ If all requests hit the SAME server = Sticky sessions working!"
echo "❌ If requests hit DIFFERENT servers = ip_hash might be disabled"
echo ""
echo "💡 To test round-robin: Comment out 'ip_hash;' in nginx/nginx.conf"
echo "   Then run: docker-compose restart nginx"
