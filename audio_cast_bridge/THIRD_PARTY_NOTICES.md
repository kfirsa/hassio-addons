# Third-party notices

## Vibecast (Cast V2 frontend)

The add-on image copies the `vibecast` binary from the published
[cast-audio-receiver-lab](https://github.com/Allcrafter1/cast-audio-receiver-lab)
OCI image (`ghcr.io/allcrafter1/cast-audio-receiver:0.6.0-dev29`). Vibecast is
maintained under the MIT license. See upstream notices in that project.

## Cast Audio Receiver Lab (reference packaging)

Architecture and player-protocol shapes are informed by
[cast-audio-receiver-lab](https://github.com/Allcrafter1/cast-audio-receiver-lab)
(MPL-2.0 for original Lab Python). This add-on does **not** vendor Lab's Python
product; it reimplements a small WebSocket client and HA output path.

## Cast authentication bundle

Certificate window material is **not** stored in this repository or the image.
On first start the add-on downloads a hash-pinned release asset from
[cast-audio-receiver-bundles](https://github.com/Allcrafter1/cast-audio-receiver-bundles)
into private add-on data. Provenance and revocation risk are documented upstream.
The material can stop working if Google changes sender policy.

## Other runtime dependencies

- ffmpeg, yt-dlp, aiohttp, websockets — Debian/upstream licenses
- Store/Ingress logo uses Google's Material Symbol `music_cast` (Apache-2.0)

Original Audio Cast Bridge manager code in this repository is provided under the
same license as the hassio-addons repository (`LICENSE` at repo root) unless noted.
