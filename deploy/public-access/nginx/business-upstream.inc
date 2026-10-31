# Include only inside reviewed business locations, never in the static root.
proxy_pass http://127.0.0.1:3200;
proxy_http_version 1.1;
proxy_set_header Host uiea-thirdhand.com;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For "";
proxy_set_header X-Forwarded-Proto https;
proxy_set_header Connection "";
proxy_connect_timeout 3s;
proxy_read_timeout 45s;
proxy_send_timeout 15s;
proxy_buffering off;
client_max_body_size 16k;
