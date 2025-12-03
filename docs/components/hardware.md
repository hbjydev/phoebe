---
icon: octicons/server-24
---

# Hardware

This page documents the hardware I use in my setup, should you want to either
reference specific parts or be insane enough to try and replicate it.

## Compute

### Intel NUC10i7FNH **(Removed!)**

This NUC _used_ to run everything, with 16GB of DDR4 RAM and an Intel i7-10710u
CPU.

However, the fan died, so no more.

### Minisforum MS-A2

My setup is powered by a [Minisforum MS-A2](https://www.minisforum.uk/products/minisforum-ms-a2?utm_source=google&utm_medium=cpcg&gad_source=1&gad_campaignid=22483783901&gbraid=0AAAAAppTh6pc9ocXOK50v93u2hw_n5qgj&gclid=CjwKCAiA3L_JBhAlEiwAlcWO5_zgpCagm8PTEDx19jqFYo7g4wMq_SySfeISsW2UYmGyFMlWs7jTHxoCx8cQAvD_BwE)
with 64GB of DDR5-5600 RAM and a Ryzen 9 9955HX (16 cores, 12 threads).

It sits on my TV unit next to the network switch it's connected to.

## Networking

### Unifi UCG Ultra

My gateway of choice was the [Unifi Cloud Gateway Ultra](https://uk.store.ui.com/uk/en/category/all-cloud-gateways/products/ucg-ultra).

It provides me with full gigabit networking, with support for a 2.5GbE WAN
uplink, easy-to-use firewalling, and a Unifi Network Controller, all in one easy
little box.

#### VLANs

I have a few VLANs I use to segregate network traffic in my home network:

| VLAN | Name | Category | CIDR | Description |
| ---- | ---- | -------- | ---- | ----------- |
| 1    | default | N/a | `192.168.0.0/21` | The VLAN all unconfigured traffic ends up on. If I've set everything up right, there should be _zero_ traffic going here. |
| 20   | IoT | Untrusted | `192.168.20.0/24` | The VLAN all my IoT devices live on. |
| 40   | Trusted | Trusted | `192.168.40.0/24` | The VLAN all of my 'trusted' devices live on. 'Trusted' here means that they're devices I know should be secure, and devices with passthrough access to the Management, DMZ and IoT VLANs. |
| 50   | Untrusted | Untrusted | `192.168.50.0/24` | The VLAN all of my 'untrusted' devices live on. This includes devices from sketchy manufacturers as well as guests on my networks, who I don't necessarily trust to keep devices secure. |
| 60   | Storage | DMZ | `10.60.0.0/24` | My Storage VLAN contains anything storage-related. This got its own VLAN because of plans I have to expand my storage setup to one of more devices. |
| 70   | Servers | DMZ | `10.70.0.0/24` | My Servers VLAN has all of my, well... servers. |
| 80*  | Service | DMZ | `10.80.0.0/24` | The Services VLAN isn't _actually_ a VLAN, it's more just a reserved space in my network for things like [Cilium](./infrastructure/cilium.md) to advertise IP addresses on that need to be routable by the rest of the network. |
| 90   | VPN | Isolated | `10.90.0.0/24` | This VLAN is configured with a [Surfshark](https://surfshark.com/) WireGuard tunnel that protects my privacy. I mainly use it for things my ISP deems 'unsafe', which is a growing list these days. |
| 99   | Management | Isolated | `10.99.0.0/24` | The VLAN all of my network devices live on. Mainly used to segregate management interfaces for things like network gear away from untrusted devices. |

### Unifi USW Lite 8 PoE

My core switch is currently the [Unifi USW Lite 8 PoE](https://uk.store.ui.com/uk/en/category/all-switching/products/usw-lite-8-poe).

### Unifi USW Flex Mini

My only leaf switch is the one sat on my desk, which is a [Unifi USW Flex Mini](https://uk.store.ui.com/uk/en/category/switching-utility/products/usw-flex-mini).

It's powered by PoE from the USW Lite 8 PoE on my TV unit.

### Unifi U6+ AP

My Wi-Fi AP is a [Unifi U6+](https://uk.store.ui.com/uk/en/category/all-wifi/products/u6-plus),
which does Wi-Fi 6 for all my devices. It currently broadcasts two networks, my
main network for client devices, and an IoT network for any 'smart' appliances
like my Apple TV 4K, my smart plugs, and any vendor-provided gear like the IHD
I got from British Gas, largely all things I don't necessarily want to be able
to talk to or see my other devices.

## Storage

### Synology DS223j

Regrettably, I went with a Synology 2-bay NAS for my networked storage solution,
which I wish I hadn't done now, but it's the [DS223j](https://www.synology.com/en-global/products/DS223j).

I regret it for a few reasons:

- It's a completely locked-down little machine (no serial, no way to install
  anything other than DSM)
- It only has 2 drive bays, which I stupidly decided to set up in RAID-0 to get
  capacity.
- DSM sucks as an OS, and is annoying to manage. It also has no ZFS support,
  which is something I'd really like to use, but can't.
