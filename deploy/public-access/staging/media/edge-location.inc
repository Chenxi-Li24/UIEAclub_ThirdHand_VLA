# Replace only the existing edge HTTPS connect/healthz location after backup.
# Keep the existing strict mTLS CA, public TLS, ACME and default-404 locations.
location ~ ^/edge/v1/(?:connect|healthz|media-grant)$ {
    proxy_pass http://$thirdhand_stage_edge_backend;
    proxy_http_version 1.1;
    proxy_set_header Host edge.uiea-thirdhand.com;
    proxy_set_header X-SSL-Client-Verify $ssl_client_verify;
    proxy_set_header X-SSL-Client-Cert $ssl_client_escaped_cert;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_connect_timeout 3s;
    proxy_read_timeout 25s;
    proxy_send_timeout 5s;
    proxy_buffering off;
}
