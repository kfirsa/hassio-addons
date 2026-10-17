# Scripts

## `test-addon-build.sh`

Builds add-on Docker images against the Home Assistant base image.

```bash
./scripts/test-addon-build.sh                  # all add-ons
./scripts/test-addon-build.sh audio_cast_bridge
```

### Before commit

Enable the repo git hook once:

```bash
git config core.hooksPath .githooks
```

Commits that stage add-on image sources (`Dockerfile`, `app/`, `rootfs/`, `config.yaml`) run this build test automatically.

Cursor agents are also gated by `.cursor/hooks.json` on `git commit`.
