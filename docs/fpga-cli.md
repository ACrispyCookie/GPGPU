# FPGA CLI flow

The `fpga:*` namespace contains board-operation tasks, separate from the Vivado
and Vitis build stages.

## Upload programming artifacts

From the repository root:

```bash
./gpgpu run vitis:build:all
./gpgpu run fpga:upload
```

`fpga:upload` transfers the existing programming artifacts via SCP to the
board-connected machine. It does **not** program the FPGA, initialize the PS,
execute the host ELF, or trigger a build. Build first; the upload checks all
three local files before starting any transfer. Every explicit invocation
uploads again, even when the files are unchanged.

With the default configuration, the mapping is:

| Local path, relative to the repository | Remote filename |
| --- | --- |
| `build/hardware/bitstream/gpgpu_block_design_wrapper.bit` | `gpgpu_platform.bit` |
| `build/software/vitis/gpgpu_platform/export/gpgpu_platform/hw/sdt/ps7_init.tcl` | `ps7_init.tcl` |
| `build/software/vitis/gpgpu_host/build/gpgpu_host.elf` | `gpgpu_host.elf` |

The default destination is `njason@192.168.1.13:/home/njason/upload/`. Renaming
the bitstream on upload keeps the existing manual programming workflow's
`gpgpu_platform.bit` filename. The bitstream comes from Vivado's published
output; do not use the obsolete Vitis platform export path
`export/gpgpu_platform/hw/sdt/gpgpu_platform.bit`.

## Configuration

Override the destination in the ignored `config/local.yaml` (merge this with
any existing local settings):

```yaml
hardware:
  fpga:
    upload:
      destination: njason@192.168.1.13
      directory: /home/njason/upload
tools:
  scp:
    command: scp
```

`destination` accepts an SSH hostname/alias or `user@host`. The remote directory
is an absolute POSIX path. Hostnames, usernames, and filenames use letters,
digits, underscores, dots, and hyphens; directory paths additionally use `/`.
Whitespace, shell metacharacters, and `..` directory components are rejected.
Use an SSH alias for IPv6 destinations or custom connection settings. SSH
aliases can supply ports and identity files via `~/.ssh/config`, without adding
credentials to this repository.

For a one-off override, global options go before `run`:

```bash
./gpgpu --set hardware.fpga.upload.destination=njason@192.168.1.13 \
  --set hardware.fpga.upload.directory=/home/njason/upload run fpga:upload
```

Local paths follow `paths.build.root`, `hardware.vivado.top`,
`hardware.vitis.platform_name`, and `hardware.vitis.host_name`. Remote bitstream
and ELF filenames follow the configured platform and host names respectively;
`ps7_init.tcl` retains its name.

## Prerequisites and failures

- The configured SCP executable must be available on the machine running the CLI.
- The remote machine must be reachable over SSH, with working authentication.
- The destination directory must already exist and be writable by the SSH user.
- Manage SSH keys and host verification through OpenSSH; no credentials are stored
  in repository configuration and host-key checking is not disabled.

A missing local artifact fails before transferring any file. A failed SCP
command stops the task with a nonzero status. The three transfers are not
atomic: earlier files may already have been replaced if a later transfer
fails. Fix the issue and rerun `fpga:upload` to resend all three files.

Upload output and failures use the same per-task logs and `run.json` metadata
as other `./gpgpu run` tasks.
