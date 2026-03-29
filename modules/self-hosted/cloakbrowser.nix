{ config, lib, pkgs, ... }:

let
  # Standalone Python script that acts as the entrypoint
  # - Cleans up stale processes and lock files
  # - Initializes the database and creates "Direct" and "VPN" profiles if missing
  # - Starts the manager on internal port 8081
  # - Provides a lightweight HTTP/WebSocket proxy on port 8080 that strips the 'Origin' header
  cloakbrowser-entrypoint = pkgs.writeText "cloakbrowser-entrypoint.py" ''
    import os
    import sys
    import subprocess
    import asyncio
    import sqlite3
    from pathlib import Path
    from aiohttp import web, ClientSession, WSMsgType

    # --- Configuration ---
    DATA_DIR = Path("/data")
    APP_DIR = Path("/app")
    PORT_PROXY = 8080
    PORT_MANAGER = 8081

    # --- Cleanup ---
    def cleanup():
        print("Cleaning up stale processes and locks...")
        # Kill stale Xvnc, Chrome, and xclip processes
        subprocess.run(["pkill", "-f", "Xvnc :[0-9]"], check=False)
        subprocess.run(["pkill", "-f", "cloakbrowser.*chrome"], check=False)
        subprocess.run(["pkill", "-f", "chromium.*fingerprint"], check=False)
        subprocess.run(["pkill", "-f", "xclip"], check=False)
        
        # Delete Chrome lock files from persistent volume
        for lock in DATA_DIR.glob("profiles/**/SingletonLock"):
            lock.unlink(missing_ok=True)
        for lock in DATA_DIR.glob("profiles/**/SingletonCookie"):
            lock.unlink(missing_ok=True)
        for lock in DATA_DIR.glob("profiles/**/SingletonSocket"):
            lock.unlink(missing_ok=True)
        
        # Clear X11 locks from /tmp
        for lock in Path("/tmp").glob(".X1*-lock"):
            lock.unlink(missing_ok=True)

    # --- Profile Management ---
    def init_profiles():
        print("Initializing database and default profiles...")
        sys.path.append(str(APP_DIR))
        try:
            from backend import database as db
            db.init_db()
            
            profiles = db.list_profiles()
            existing_names = {p['name'] for p in profiles}
            
            if "VPN" not in existing_names:
                print("Creating VPN profile...")
                db.create_profile(
                    name="VPN", 
                    proxy="http://gluetun:8888", 
                    humanize=True, 
                    geoip=True, 
                    platform="windows"
                )
                print("VPN profile created.")
            
            if "Direct" not in existing_names:
                print("Creating Direct profile...")
                db.create_profile(
                    name="Direct", 
                    proxy=None, 
                    humanize=True, 
                    geoip=True, 
                    platform="windows"
                )
                print("Direct profile created.")
        except Exception as e:
            print(f"Failed to initialize profiles: {e}")
            # Non-critical, the manager should still start
            pass

    # --- Origin-Stripping Proxy ---
    async def proxy_handler(request):
        url = f"http://127.0.0.1:{PORT_MANAGER}''${request.rel_url}"
        # Strip 'Origin' to bypass CSWSH checks in the manager
        headers = {k: v for k, v in request.headers.items() if k.lower() != 'origin'}
        
        # WebSocket support for CDP and VNC
        if request.headers.get('Upgrade', '').lower() == 'websocket':
            ws_server = web.WebSocketResponse()
            await ws_server.prepare(request)
            
            async with ClientSession() as session:
                async with session.ws_connect(url, headers=headers) as ws_client:
                    async def forward(src, dst):
                        try:
                            async for msg in src:
                                if msg.type == WSMsgType.TEXT:
                                    await dst.send_str(msg.data)
                                elif msg.type == WSMsgType.BINARY:
                                    await dst.send_bytes(msg.data)
                                elif msg.type == WSMsgType.CLOSE:
                                    await dst.close()
                                    break
                                elif msg.type == WSMsgType.ERROR:
                                    break
                        except Exception:
                            pass
                    
                    await asyncio.gather(
                        forward(ws_server, ws_client),
                        forward(ws_client, ws_server)
                    )
            return ws_server
        
        # Standard HTTP proxying
        async with ClientSession() as session:
            try:
                async with session.request(
                    method=request.method,
                    url=url,
                    headers=headers,
                    data=await request.read(),
                    allow_redirects=False
                ) as resp:
                    body = await resp.read()
                    return web.Response(
                        body=body,
                        status=resp.status,
                        headers=resp.headers
                    )
            except Exception as e:
                return web.Response(text=f"Proxy error: {e}", status=502)

    async def main():
        cleanup()
        init_profiles()
        
        print(f"Starting manager on 127.0.0.1:{PORT_MANAGER}...")
        manager_proc = await asyncio.create_subprocess_exec(
            "uvicorn", "backend.main:app", 
            "--host", "127.0.0.1", 
            "--port", str(PORT_MANAGER), 
            "--log-level", "warning",
            cwd=str(APP_DIR)
        )
        
        print(f"Starting Origin-stripping proxy on 0.0.0.0:{PORT_PROXY}...")
        proxy_app = web.Application()
        proxy_app.router.add_route('*', '/{path:.*}', proxy_handler)
        
        runner = web.AppRunner(proxy_app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', PORT_PROXY)
        await site.start()
        
        print("CloakBrowser is ready and accepting connections!")
        
        try:
            # Keep the script running as long as the manager is alive
            await manager_proc.wait()
        except (asyncio.CancelledError, KeyboardInterrupt):
            print("Shutting down...")
            manager_proc.terminate()
            await manager_proc.wait()
            await runner.cleanup()

    if __name__ == "__main__":
        asyncio.run(main())
  '';

in
{
  # CloakBrowser Manager
  virtualisation.oci-containers.containers."cloakbrowser" = {
    image = "cloakhq/cloakbrowser-manager:latest";
    extraOptions = [ "--network=ghostship_net" ];
    
    # Run the custom entrypoint script
    entrypoint = "/usr/local/bin/python3";
    cmd = [ "/cloakbrowser-entrypoint.py" ];

    volumes = [
      "/srv/apps/cloakbrowser/data:/data"
      "${cloakbrowser-entrypoint}:/cloakbrowser-entrypoint.py:ro"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/cloakbrowser 0755 apps apps -"
    "d /srv/apps/cloakbrowser/data 0755 apps apps -"
  ];
}
