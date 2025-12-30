"""Example demonstrating server discovery."""

import asyncio
from aiosendspin_sounddevice import (
    SendspinAudioClient,
    SendspinAudioClientConfig,
    ServiceDiscovery,
)


async def example_one_time_discovery():
    """Discover servers once and connect to the first one."""
    print("Discovering servers...")
    servers = await ServiceDiscovery.discover_servers(discovery_time=3.0)

    if not servers:
        print("No servers found!")
        return

    print(f"Found {len(servers)} server(s):")
    for server in servers:
        print(f"  - {server.name} at {server.url}")

    # Connect to the first discovered server
    server = servers[0]
    print(f"\nConnecting to {server.name}...")

    config = SendspinAudioClientConfig(
        url=server.url,
        client_id="discovery-client",
        client_name="Discovery Example",
    )

    client = SendspinAudioClient(config)

    try:
        await client.connect()
        print("Connected! Playing audio... Press Ctrl+C to stop")
        try:
            await client.wait_for_disconnect()
        except asyncio.CancelledError:
            pass
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        await client.disconnect()


async def example_continuous_discovery():
    """Use ServiceDiscovery for continuous discovery."""
    discovery = ServiceDiscovery()

    try:
        print("Starting continuous discovery...")
        await discovery.start()

        print("Waiting for first server...")
        url = await discovery.wait_for_first_server()
        print(f"Found server at: {url}")

        # Get all discovered servers
        servers = discovery.get_servers()
        print(f"Total servers discovered: {len(servers)}")

        # Connect to the discovered server
        config = SendspinAudioClientConfig(
            url=url,
            client_id="continuous-discovery-client",
            client_name="Continuous Discovery Example",
        )

        client = SendspinAudioClient(config)

        try:
            await client.connect()
            print("Connected! Playing audio... Press Ctrl+C to stop")
            try:
                await client.wait_for_disconnect()
            except asyncio.CancelledError:
                pass
        except KeyboardInterrupt:
            print("\nStopping...")
        finally:
            await client.disconnect()

    finally:
        await discovery.stop()


async def main():
    """Run discovery examples."""
    print("=== One-time Discovery Example ===\n")
    await example_one_time_discovery()

    print("\n=== Continuous Discovery Example ===\n")
    await example_continuous_discovery()


if __name__ == "__main__":
    asyncio.run(main())

