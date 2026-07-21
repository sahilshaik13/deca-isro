#!/bin/bash

# Securely prompt for the password once
echo -n "Enter the sudo password: "
read -s PASSWORD
echo ""

STATIONS=("station1" "station2")

for H in "${STATIONS[@]}"; do
    echo "Updating $H..."
    
    # Send the commands via SSH using the -S flag to read password from stdin
    # We use a single string so the password pipe applies to everything
    echo "$PASSWORD" | ssh -t $H 'sudo -S mkdir -p /usr/local/bin && \
    sudo -S mv /etc/rc.local /usr/local/bin/setup_namespaces.sh 2>/dev/null && \
    sudo -S chmod +x /usr/local/bin/setup_namespaces.sh && \
    sudo -S bash -c "cat > /etc/systemd/system/deca-namespaces.service << EOT
[Unit]
Description=DECA CE Namespaces and iPerf Server
After=network-online.target frr.service systemd-networkd.service
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/setup_namespaces.sh
ExecStartPost=/usr/bin/systemctl restart frr

[Install]
WantedBy=multi-user.target
EOT" && \
    sudo -S systemctl daemon-reload && \
    sudo -S systemctl enable --now deca-namespaces.service'
    
    echo "$H updated successfully."
done

echo "Boot fix applied. Running diagnostics..."
check stations
