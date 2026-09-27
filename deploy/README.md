# Hosting on a Mac mini with Cloudflare Tunnel

```
visitor ──HTTPS──▶ Cloudflare ──tunnel──▶ cloudflared (Mac mini) ──▶ Caddy 127.0.0.1:8080 ──▶ dist/
```

- **Caddy** serves the built site. It listens on `127.0.0.1`, so nothing on your network can reach it
  directly.
- **cloudflared** opens an *outgoing* connection to Cloudflare. No router port forwarding, no
  public IP address, and your home address stays hidden. Cloudflare provides HTTPS and caching.
- Both run as boot-time services: after a power cut or an update the site comes back by itself,
  without anyone logging in.

You edit and build on your own computer and publish to the Mac with one command.

## What you need

- The Mac mini, with [Homebrew](https://brew.sh) installed.
- A domain whose DNS is managed by Cloudflare (the free plan is enough). To add one, go to the
  Cloudflare dashboard → *Add a domain* and switch the domain's nameservers at your registrar.
  To try things first without a domain, see [step 3](#3-put-it-on-the-internet).

## 1. Prepare the Mac (once)

On the Mac mini:

1. **System Settings → General → Sharing → Remote Login**: on. This lets you publish from your computer.
2. **System Settings → Energy**: turn on *Prevent automatic sleeping when the display is off* and
   *Start up automatically after a power failure*. A sleeping Mac is an offline website.
3. Note the Mac's address, shown under Remote Login (for example `you@mac-mini.local`).

On your computer, set up key login so publishing doesn't ask for a password each time:

```bash
ssh-copy-id you@mac-mini.local
```

## 2. Copy the site over and start the web server

From the project folder on your computer:

```bash
deploy/publish.sh you@mac-mini.local
```

This builds the site and copies the project to `~/insignia-web` on the Mac. Then run the one-time
setup on the Mac. It asks for the Mac's password once, to install the services:

```bash
ssh -t you@mac-mini.local '~/insignia-web/deploy/mac-setup.sh'
```

The setup installs Caddy and cloudflared, starts the web server as a service and checks that it
answers. Keep the project in `~/insignia-web`, not in Documents, Desktop or Downloads: macOS stops
background services from reading those folders.

## 3. Put it on the internet

**Quick test, no domain needed.** On the Mac:

```bash
cloudflared tunnel --url http://127.0.0.1:8080
```

It prints a temporary `https://….trycloudflare.com` address. The address changes every time and
the tunnel stops when you close the terminal (Ctrl+C), so it's only for testing.

**Permanent address:**

1. In the Cloudflare dashboard go to **Networking → Tunnels → Create a tunnel**, choose
   *Cloudflared* and name it (for example `insignia`).
2. On the install screen choose **macOS**. The command shown ends in a long token (`eyJ…`). Copy
   only the token. Keep it private: anyone who has it can run your tunnel.
3. On the Mac, run the setup again with the token. This installs cloudflared as a boot-time
   service:

   ```bash
   ~/insignia-web/deploy/mac-setup.sh eyJ...your-token...
   ```

   The dashboard should now show the tunnel as **Healthy**.
4. In the tunnel, open **Routes → Add route → Published application**:
   - **Subdomain / Domain**: for example `www` · `yourdomain.com`, or leave Subdomain empty for the bare domain
   - **Service URL**: `http://127.0.0.1:8080`

Your site is live at that address within a minute or so.

## 4. Tell the site its address

In `content/site.yaml`, set the public address so link previews on social media work. Keep
`base_url` empty, because the site sits at the root of the domain:

```yaml
base_url: ""
site_url: "https://www.yourdomain.com"
```

Then publish again.

## Updating the site

```bash
deploy/publish.sh you@mac-mini.local
```

The change is live as soon as the copy finishes. Nothing needs restarting. To save typing, run
`export INSIGNIA_HOST=you@mac-mini.local` in your shell profile; after that plain
`deploy/publish.sh` is enough.

## Managing it (on the Mac)

| Task | Command |
|---|---|
| Web server log | `tail -f ~/Library/Logs/insignia-web.log` |
| Tunnel log | `tail -f /Library/Logs/com.cloudflare.cloudflared.err.log` |
| Restart web server (after editing `deploy/Caddyfile`) | `sudo launchctl kickstart -k system/com.insignia.web` |
| Restart tunnel | `sudo launchctl kickstart -k system/com.cloudflare.cloudflared` |
| Is the site being served? | `curl -I http://127.0.0.1:8080/` |
| Remove web server service | `sudo launchctl bootout system/com.insignia.web && sudo rm /Library/LaunchDaemons/com.insignia.web.plist` |
| Remove tunnel service | `sudo cloudflared service uninstall` |

**Troubleshooting**

- **Dashboard says the tunnel is down.** Check the tunnel log. If it stopped working after a
  `brew upgrade`, run `mac-setup.sh <TOKEN>` again. To get the token again, open the tunnel in the
  dashboard and view its install command.
- **Error 502 / "Bad gateway".** The tunnel works but the web server doesn't answer. Check
  `curl -I http://127.0.0.1:8080/` and the web server log.
- **"Operation not permitted" in the web server log.** The project is in a protected folder. Move
  it to `~/insignia-web` and run `mac-setup.sh` again.
- **FileVault.** If disk encryption is on, a restarted Mac waits at the login screen before
  anything starts, including these services. For restarts you plan, `sudo fdesetup authrestart`
  unlocks the disk for the next boot.

## Editing on the Mac instead

If you'd rather write on the Mac mini itself, install the build tools once:

```bash
xcode-select --install
pip3 install --user -r requirements.txt
```

Then `python3 build.py` in `~/insignia-web` updates the live site directly. `python3 build.py serve`
still gives you a private preview at `http://localhost:8000`.

Pick one place to edit. `publish.sh` makes the Mac's copy an exact mirror of your computer's copy,
so it overwrites anything you changed directly on the Mac.
