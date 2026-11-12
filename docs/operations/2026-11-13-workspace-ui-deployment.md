# Ubuntu workspace UI deployment

Target: nieqingcao@100.85.63.78, repository /home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA.

The previous browser preview was a static Windows server without live APIs or model routes. The Ubuntu gateway runs under thirdhand-web-grasp-live.service on 127.0.0.1:9983. Tailscale Serve still targeted the previous LAN address; its HTTP 9983 target was corrected to http://127.0.0.1:9983. The tailnet hostname is ubuntu.taild18ef7.ts.net; a raw IP request is not matched by this Serve configuration.

Uploaded the tracked public frontend at commit 67e14c4. The remote index additions (raise/level stages) are present in the new index. A three-way comparison of remote main.js against its cf6a9eec base and the new frontend merged cleanly and matched the new main.js. Other uncommitted robot, speech, grasp and runtime configuration changes were retained.

Added system-ready.js and injected its handler into the existing gateway rather than replacing the backend. Restarted only thirdhand-web-grasp-live.service; it returned active/running. No robot connection, motion, homing or gripper requests were issued. Initial service inspection showed existing robot connectivity and idle depth/following states.

Local frontend startup now reuses the existing compressed GLB model loader instead of downloading approximately 22 MB of raw STL meshes. Uploaded assets/robot/startouch-v3/web/robot-visuals.glb (3,050,660 bytes). The local remote-access loader allows 120 seconds; the cloud loader retains its 15-second default.

Backup: /home/nieqingcao/.local/share/thirdhand-ui-backups/20261113-67e14c4/before.tgz contains the prior public directory and gateway server.js. Restore that archive from the repository root and restart the web unit to roll back those files; the added system-ready module and GLB can remain unused. No database or credentials were changed.

Windows access uses an SSH forwarding session: ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L 127.0.0.1:18984:127.0.0.1:9983 nieqingcao@100.85.63.78. Open http://127.0.0.1:18984. This is the Ubuntu API via SSH, not the static preview at port 18983. The forwarding process must remain running. Localhost also allows browser microphone permissions.

Known pre-existing service limits: grasp reports unavailable and TCP calibration is disabled in the current gateway configuration. This deployment does not silently enable or replace those configurations. Full speech-model inference and physical hardware acceptance are separate from frontend connectivity verification.

Live acceptance: the compact GLB SHA-256 matched locally and remotely (b4fc6716a5b460c0fd38ea25bf66936e0385d128e8028ef6513b146cc6f0f1cd). Browser rendered the robot and six joint controls, reported Startouch/can0, SDK Online, Web Online and AI connected. A text-only greeting explicitly excluding robot actions returned “Hello! How can I help you today?” with no candidate. Twenty-five focused tests passed. Microphone recording and physical movements were not tested. Hidden vision-page MJPEG downloads are now paused to avoid saturating the Tailscale relay; selecting the vision page resumes them.

After reloading with the hidden-stream fix, browser acceptance returned HTTP 200 from /api/system-ready in 280 ms (available=true, overall=unchecked). No CJK characters were present in visible page text. Switching from overview to digital twin kept the chat visible, centered at the bottom (720 by 76 pixels in a 2558 by 1248 viewport). Preparation remains unchecked until explicitly requested; this validation did not start preparation or move hardware.
