# Initial Concept

I am switching my personal dev and server environments from arch/ubuntu to nixos. This is going to be done from scratch but I have old configuration repos that used ansible to configure my old environment. Help me get my nixos repo setup so I can start using it to configure my environments. The old ansible code is in the old directory which is just here for reference.

# Product Guide: Unified NixOS Configuration Repository

## Vision
To create a robust, modular, and reproducible NixOS configuration repository that manages a diverse fleet of systems—including personal workstations, servers, and embedded devices—replacing a legacy Ansible-based infrastructure with a modern, declarative Nix-native approach.

## Target Systems
- **Workstations/Laptops**: High-performance personal development environments with GUI and desktop tools.
- **Servers/Home Lab**: Headless service hosting and infrastructure management.
- **Embedded/ARM**: Lightweight configurations for devices like Raspberry Pi.
- **Emulation PC**: Dedicated hardware (e.g., Minisforum HX100G) optimized for high-performance gaming and emulation.

## System Profiles

### boomer-kuwanger
- **Purpose**: Dedicated emulation-focused NixOS PC.
- **Hardware**: Minisforum Neptune HX100G.
    - **CPU**: AMD Ryzen 7 7840HS (8 Cores/16 Threads, up to 5.1 GHz, 4nm).
    - **GPU (Integrated)**: AMD Radeon 780M.
    - **GPU (Dedicated)**: AMD Radeon RX 6650M (8GB GDDR6, up to 100W TDP).
    - **RAM**: Supports up to 64GB DDR5 (5600MHz).
    - **Storage**: Dual M.2 2280 PCIe 4.0 SSD slots.
    - **Networking**: 1x RJ45 2.5 Gigabit Ethernet.
    - **WiFi/Bluetooth**: AMD RZ616 (MediaTek MT7922) Wi-Fi 6E & Bluetooth 5.2/5.3.
- **Optimization Strategy**: 
    - Configuration should be optimized for emulation (e.g., low-latency input, optimized Vulkan/OpenGL performance).
    - **Bluetooth Tuning**: The AMD RZ616 (MT7922) requires careful power management on Linux. Disable USB autosuspend for `btusb` and consider disabling ASPM for `mt7921e` if connection drops occur.
    - Support production hardware (AMD) with native optimizations.

### chill-penguin
- **Purpose**: High-performance headless server for media, home automation, and Docker containers.
- **Hardware**: Mac Studio (M1 Ultra).
    - **Architecture**: aarch64 (16k page size).
    - **Storage**: 4TB NVMe SSD.
    - **Networking**: 10GbE, WiFi 6E/BT 5.3.
- **Implementation Strategy**: Clean NixOS installation using official `nixos-apple-silicon` project.
    - Headless server deployment via cross-compiled ARM64 installer.
    - Leverage Btrfs subvolumes for data isolation and snapshots.
    - Declaratively manage all application configurations and secrets.
- **Kernel & Hardware Support**:
    - **Kernel**: Official Asahi 6.19.9 kernel provided by the `nixos-apple-silicon` project.
    - **Boot Flow**: m1n1 (Stage 1) -> m1n1 (Stage 2 payload: boot.bin) -> U-Boot -> systemd-boot -> Kernel.
    - **Multi-Die Support**: Full utilization of the M1 Ultra multi-die architecture (20 cores, 48-core GPU).
    - **Peripheral Firmware**: Automatically extracted from `/boot/asahi/` and deployed uncompressed for maximum compatibility.

### launch-octopus
- **Purpose**: Primary WSL2 development environment on Windows 11.
- **Integration**: Deep WSL2-to-Windows integration (notifications, file sharing).

### armored-armadillo
- **Purpose**: Desktop WSL2 development environment on Windows 11.
- **Integration**: Full WSL2-to-Windows integration, functionally identical to launch-octopus.

## Primary Objectives
- **Absolute Reproducibility**: Ensure that any system can be rebuilt from scratch to an identical state using the configuration.
- **Comprehensive Dotfile Management**: Use Home Manager to manage user environments, shell configurations, and application settings declaratively.
- **Efficient Remote Deployment**: Enable seamless updates and configuration deployments to remote servers and devices.
- **Seamless Platform Integration**: Implement deep integration between guest environments (e.g., WSL2) and host systems (Windows) for notifications, file sharing, and interoperability.

## Key Features
- **Nix Flakes**: Utilize the modern Flakes ecosystem for dependency management and standardized outputs.
- **Home Manager Integration**: Deeply integrate user-level configurations into the system-wide Nix modules.
- **Secrets Management**: Implement a secure solution (e.g., sops-nix or agenix) for managing sensitive data like API keys and passwords.
- **AI & Browser Automation**: Integration of Model Context Protocol (MCP) servers (e.g., browser-use) to enable advanced AI-driven research and automation workflows.
- **Gemini Global Instructions**: A centralized, distilled collection of expert personas and system-native workflows managed via Home Manager to enhance AI-driven development.

## Architecture & Constraints
- **Modular Architecture**: Maintain a strict separation between hardware-specific logic, shared system modules, and user configurations.
- **Multi-host Support**: Support multiple distinct host configurations within a single flake-based repository using shared logic.
- **Rollback Capability**: Leverage NixOS's native generational rollbacks to ensure system stability and recovery.
