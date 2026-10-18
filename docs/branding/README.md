# SolarTT-UI artwork

Project logo: a solar corona around a tunnel entrance. It uses the panel palette:
navy charcoal `#11151d` and warm amber `#ffbc72`. The artwork was generated using
the built-in imagegen tool for SolarTT-UI; no upstream TrustTunnel logo was used.
It is distributed with the project's Apache-2.0 license. It is not a claim of
endorsement by TrustTunnel or a grant of rights to another project's trademarks.

## Files

- [solartt-avatar.png](solartt-avatar.png): square logo for the README or a
  project-specific organization/channel avatar.
- [solartt-social-preview.png](solartt-social-preview.png): 2:1 repository link
  preview, below 1,000,000 bytes and above GitHub's recommended minimum size.
- [source/](source/): unchanged generated PNG originals, including their original
  C2PA metadata. These sources are larger than the preview upload limit.
- [prompts.md](prompts.md): the generation prompts and the logo reference used
  for the selected banner.

## GitHub configuration

A repository uses its owner's avatar; this artwork does not change the personal
avatar for `precox`. The README already displays the project logo. To configure
link cards, the repository owner should download `solartt-social-preview.png`,
then open **Settings → General → Social preview → Edit → Upload an image**.

The current GitHub connector and repository deploy key do not provide an
administrative image-upload action. Committing this file alone does not set the
repository's Social preview. Updating a README does not change an already cached
Telegram/social-platform preview either.

See [GitHub's official social-preview instructions](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/customizing-your-repositorys-social-media-preview).

## Lossless delivery export

`python3 docs/branding/export.py` recompresses the PNG IDAT container with zlib
level 9. It verifies unchanged IHDR and byte-identical decompressed pixel/filter
data: no resize, redraw, retouching or color change. The original generated
artwork remains untouched in `source/`.

Recompression changes the file-level C2PA binding, so the original manifest is
retained with the original file and not copied into the derivative export as an
invalid claim. No generated content is hidden: the prompts and original sources
are preserved here. The repository README consumes the smaller delivery export;
documentation/artwork updates do not replace previously tagged release packages.
