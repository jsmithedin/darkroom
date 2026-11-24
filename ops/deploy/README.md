# Deploying and watching Darkroom (pull-based)

A timer on the NUC runs `deployer.py` every 5 minutes. Nothing listens, no GitHub runner is
installed and no GitHub token exists on the host; it only makes outbound requests to GitHub
(public API, no credentials) and Telegram.

## What it does

**Deploy** (`darkroom-deploy.timer`): asks GitHub for the tip of `main`. It deploys only if
that commit is not already running, GitHub shows it as **verified** (merges made through
GitHub are signed by GitHub), and all of `backend`, `frontend`, `image` and `skills` finished
**successfully on that exact commit**. Then it fetches the commit, checks it is on
`origin/main`, takes a **database backup** (stopping if that fails), runs
`docker compose up -d --build`, and waits up to 90 s for the app's health check (and the public
URL). If the new version is not healthy it **rolls back** to the previous commit and tells you.
A commit that failed is not retried. Telegram messages: deploying, deployed, failed (with the
rollback result), refused (failed checks or unverified), backup failed.

**Health** (`darkroom-health.timer`): checks that the `app` and `db` containers are running and
that `/api/health` reports the database up, inside the container and through the public URL.
Two failures in a row (about 10 minutes) send "DOWN" with what is wrong; a reminder follows every
6 hours while it stays down; one message when it recovers. A single blip is silent. It skips
quietly while a deploy is running so a restart is not reported as an outage.

What it cannot see: the NUC itself being off or offline (nothing is left running to tell you).
Add an outside monitor (for example a free uptime check on `https://film.jamielab.uk/api/health`)
if you want that covered.

## Setup on the NUC

Needs Docker with compose, git and Python 3.10 or newer (`python3 --version`).

1. **User and directory** (the user can control Docker, so treat it as privileged; it has no login):
   ```
   sudo useradd -r -m -s /usr/sbin/nologin -G docker darkroom-deploy
   sudo install -d -o darkroom-deploy -g darkroom-deploy -m 755 /opt/darkroom
   sudo -u darkroom-deploy git clone https://github.com/jsmithedin/darkroom.git /opt/darkroom/repo
   sudo install -d -o darkroom-deploy -g darkroom-deploy -m 750 /var/lib/darkroom-deploy
   ```
   The last line is where the script keeps its state (what is deployed, what failed, alert history). systemd would create it for the timers, but the manual test commands below run outside systemd and need it to exist.
2. **App environment file** (the real `.env`, outside the checkout):
   ```
   sudo cp /path/to/current/.env /opt/darkroom/.env
   sudo chown darkroom-deploy:darkroom-deploy /opt/darkroom/.env && sudo chmod 600 /opt/darkroom/.env
   ```
3. **Find the running stack's project name**: `docker compose ls`. If it is not `darkroom`, put
   the real name in `COMPOSE_PROJECT_NAME` in the next step, or the deploy will start an empty
   database. Do not run `docker compose down -v`.
4. **Telegram:** message @BotFather, `/newbot`, keep the token. Send your new bot any message,
   then open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and read
   `"chat":{"id":...}`. Keep the token private (do not paste it into issues or chats).
   ```
   sudo install -m 600 -o root -g root /opt/darkroom/repo/ops/deploy/env.example /etc/darkroom-deploy.env
   sudo nano /etc/darkroom-deploy.env      # fill in the token, chat id and project name
   ```
5. **Test Telegram** (this loads the file as root, then drops to the deploy user):
   ```
   sudo bash -c 'set -a; . /etc/darkroom-deploy.env; exec sudo -u darkroom-deploy --preserve-env /usr/bin/python3 /opt/darkroom/repo/ops/deploy/deployer.py test-notify'
   ```
6. **Tell it what is running now.** Check out the commit the live stack was built from and
   record it, so a first failed deploy has something to roll back to (skip this if you do not
   know; the first deploy then has no rollback):
   ```
   sudo -u darkroom-deploy git -C /opt/darkroom/repo checkout --detach <commit>
   sudo bash -c 'set -a; . /etc/darkroom-deploy.env; exec sudo -u darkroom-deploy --preserve-env /usr/bin/python3 /opt/darkroom/repo/ops/deploy/deployer.py adopt'
   ```
7. **Dry run** (prints what it would do, changes nothing):
   ```
   sudo bash -c 'set -a; . /etc/darkroom-deploy.env; exec sudo -u darkroom-deploy --preserve-env /usr/bin/python3 /opt/darkroom/repo/ops/deploy/deployer.py deploy --dry-run'
   ```
8. **Install the timers:**
   ```
   sudo cp /opt/darkroom/repo/ops/deploy/darkroom-{deploy,health}.{service,timer} /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now darkroom-deploy.timer darkroom-health.timer
   ```
9. **Stop any older way of deploying** (a manual `docker compose up` habit, or an unmerged
   self-hosted-runner workflow) so two things do not fight over the containers.

## Checking it works
- `systemctl list-timers 'darkroom-*'` shows both timers; `journalctl -u darkroom-deploy -u darkroom-health -f` follows them.
- **Deploy:** merge a trivial change. Within about 5 minutes after CI is green you should get "deploying" then "deployed and healthy", and `/api/health` still returns `"db":true`.
- **Down alert:** `docker compose -p darkroom stop app`. Within about 10 minutes you get "DOWN: container not running: app". Start it again and you get "back up". (Run it as the deploy user, or with `sudo`.)
- Rollback and refusal paths are covered by tests (`backend/tests/ops/`) but not worth breaking production to try.

## Operating it
- **Pause deploys:** `sudo systemctl stop darkroom-deploy.timer` (start it to resume).
- **Retry a commit that failed:** fix forward by merging a new commit, or edit `failed_sha` out of `/var/lib/darkroom-deploy/state.json`.
- **Roll back by hand:** `sudo -u darkroom-deploy git -C /opt/darkroom/repo checkout --detach <good commit>`, then `docker compose -p darkroom --project-directory /opt/darkroom/repo --env-file /opt/darkroom/.env up -d --build`, and stop the deploy timer or revert on `main` so it does not move forward again. A migration from a bad version may already have run: restore from a backup (see the main README) if the schema is wrong.
- **Restore a backup:** the pre-deploy backup is in `./backups` of the checkout's compose project; see "Backups and restore" in the main README.

## Security notes
- The units keep `NoNewPrivileges`, `PrivateTmp` and `ProtectSystem=full`. `ProtectHome=yes` was removed: under it `docker compose` failed inside the service (but worked by hand) because Docker could not read its config from the user's home. The deploy user can control Docker, so that setting added little protection anyway.
- Anyone who can merge to `main` can run code on the NUC, as with any auto-deploy. `main` is protected (PRs only, all four checks required, admins included); keep two-factor on the GitHub account and read dependency update PRs before merging them.
- Only the tip of `main` is deployed, and only with a GitHub-verified signature and green checks on that commit. If GitHub stopped signing merges, deploys would refuse and tell you (`REQUIRE_VERIFIED=0` turns the check off).
- The Telegram token lives in a root-only file read by systemd. If it leaks, revoke it with @BotFather.
- Requires the GitHub API to be reachable; if it is not, nothing happens and nothing alerts (the health check still runs).
