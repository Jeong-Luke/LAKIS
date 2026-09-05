# Third-party notices

LAKIS installs compatible third-party components from their official upstream locations at versions tested with each LAKIS release.

For every dependency, the release manifest will record:

- project and author name;
- exact release or commit;
- official source URL;
- license URL and attribution;
- SHA-256 checksum;
- whether a LAKIS fallback mirror is legally permitted.

Fallback copies will not be published for components whose licenses do not permit redistribution. Such components will remain available only through their official publisher.

The Windows installer embeds the official `7zr.exe` command-line extractor from
[7-Zip](https://www.7-zip.org/). 7-Zip is free software; most of its code is
licensed under the GNU LGPL, with portions under the BSD 3-clause license and
the unRAR license restriction. The unmodified executable is downloaded from
the official publisher and verified by SHA-256 during the release build.
