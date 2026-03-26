# Implementation Plan: Setup Hyper-V Dev VM (boomer-kuwanger-dev)

## Phase 1: NixOS Host Configuration [checkpoint: 06cea5c]
- [x] Task: Create host configuration directory `hosts/boomer-kuwanger-dev` [6c38dd6]
    - [ ] Initialize `default.nix` by adapting from `hosts/boomer-kuwanger/default.nix`
    - [ ] Create `hardware-configuration.nix` with Hyper-V specific modules (`hyperv-guest`)
- [x] Task: Define the host in `flake.nix` [41e2467]
    - [ ] Add `boomer-kuwanger-dev` to `nixosConfigurations`
- [x] Task: Conductor - User Manual Verification 'Phase 1: NixOS Host Configuration' (Protocol in workflow.md)

## Phase 2: Hyper-V Resource Provisioning
- [x] Task: Create the Hyper-V Virtual Machine [cba3cbb]
    - [ ] Verify if VM name 'boomer-kuwanger-dev' already exists
    - [ ] Create VM with 8GB RAM, 4 vCPUs, and Generation 2 settings
    - [ ] Create 64GB VHDX and attach to VM
- [~] Task: Configure Boot Media
    - [ ] Attach ISO: `/home/nixos/win-home/Downloads/nixos-minimal-25.11.7198.71caefce12ba-x86_64-linux.iso`
    - [ ] Set DVD as the first boot device
- [ ] Task: Conductor - User Manual Verification 'Phase 2: Hyper-V Resource Provisioning' (Protocol in workflow.md)

## Phase 3: Initial Bootstrap & Connectivity
- [ ] Task: Start and Verify Boot
    - [ ] Start the VM
    - [ ] Confirm VM reaches the NixOS installer shell
- [ ] Task: Final Verification & Metadata
    - [ ] Confirm basic network connectivity within the VM
    - [ ] Update project documentation with new host details
- [ ] Task: Conductor - User Manual Verification 'Phase 3: Initial Bootstrap & Connectivity' (Protocol in workflow.md)

## Phase 4: NixOS Installation
- [ ] Task: Prepare Partitions
    - [ ] Partition the disk (GPT, EFI, Root)
    - [ ] Format partitions (FAT32 for EFI, Ext4 for Root)
    - [ ] Mount partitions to `/mnt`
- [ ] Task: Perform Installation
    - [ ] Execute `nixos-install --flake .#boomer-kuwanger-dev` from the installer environment
- [ ] Task: Post-Installation Reboot
    - [ ] Unmount and reboot the VM
    - [ ] Confirm the VM boots into the installed system
- [ ] Task: Conductor - User Manual Verification 'Phase 4: NixOS Installation' (Protocol in workflow.md)
