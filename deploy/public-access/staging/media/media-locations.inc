# Include only inside staging.uiea-thirdhand.com's existing HTTPS server.
location = /internal/v1/media-auth {
    internal;
    access_log off;
    error_log /dev/null crit;
    proxy_pass http://127.0.0.1:3202/internal/v1/media-auth;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
    proxy_set_header Host staging.uiea-thirdhand.com;
    proxy_set_header Cookie $http_cookie;
    proxy_set_header X-Original-URI $request_uri;
    proxy_set_header X-Original-Origin $http_origin;
    proxy_set_header X-Original-Sec-Fetch-Site $http_sec_fetch_site;
    proxy_set_header X-Original-Authorization $http_authorization;
}
location ~ ^/media/rtc(?:/v1)?(?:/validate)?$ {
    access_log off;
    error_log /dev/null crit;
    auth_request /internal/v1/media-auth;
    rewrite ^/media/(.*)$ /$1 break;
    proxy_pass http://127.0.0.1:7880;
    proxy_http_version 1.1;
    proxy_set_header Host staging.uiea-thirdhand.com;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $thirdhand_stage_media_connection;
    proxy_connect_timeout 2s;
    proxy_read_timeout 30s;
    proxy_send_timeout 5s;
    proxy_buffering off;
}
