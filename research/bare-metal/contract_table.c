/*
 * NEXUS OS Contract Syscall Table
 *
 * Replaces the traditional Linux syscall_table[] with a mapping
 * from syscall numbers to Ethereum smart contract addresses and
 * function selectors.
 *
 * This is the core data structure that makes "blockchain IS the kernel"
 * literal — every syscall is a contract call.
 *
 * In a full implementation, the syscall handler (from exception vector)
 * would look up this table and route to the corresponding contract.
 */

#include "contract_table.h"

/* Forward declaration for UART output */
extern void uart_puts(const char *s);
extern void uart_put_hex(unsigned long val);
extern void uart_put_dec(unsigned long val);

/*
 * Contract addresses (from deployed contracts on NEXUS chain):
 *
 * PidRegistry:     deployed in this section (address filled after deploy)
 * StorageRegistry: 0xd216DABDAbE314337B4821D29C26FeB52Cb37d27
 * AgentGovernance: 0xA4f8CA77065bE462324624083990F58ff1f12207
 * TokenManager:    0x08C96540A286a6b3cDe1E20F77B246E53D238E48
 *
 * Syscall mapping rationale:
 *   20  (getpid)  → PidRegistry.getPid() — process identity
 *   39  (getuid)  → AgentGovernance.getRole() — identity/auth
 *   2   (open)    → StorageRegistry.registerFile() — file access
 *   63  (read)    → StorageRegistry.getFileHash() — data integrity
 *   64  (write)   → StorageRegistry.updateFile() — data mutation
 *   172 (reboot)  → AgentGovernance.proposeShutdown() — governance
 */

/* PidRegistry: 0xdE9DC5FB0386Cf92145d36e6d46f2a3FA8b531AA */
static unsigned char pid_registry_addr[20] = {
    0xdE, 0x9D, 0xC5, 0xFB, 0x03, 0x86, 0xCf, 0x92,
    0x14, 0x5d, 0x36, 0xe6, 0xd4, 0x6f, 0x2a, 0x3f,
    0xA8, 0xb5, 0x31, 0xAA
};

static unsigned char storage_registry_addr[20] = {
    0xd2, 0x16, 0xDA, 0xBD, 0xAb, 0xE3, 0x14, 0x33,
    0x7B, 0x48, 0x21, 0xD2, 0x9C, 0x26, 0xFe, 0xB5,
    0x2C, 0xb3, 0x7d, 0x27
};

static unsigned char agent_governance_addr[20] = {
    0xA4, 0xf8, 0xCA, 0x77, 0x06, 0x5b, 0xE4, 0x62,
    0x32, 0x46, 0x24, 0x08, 0x39, 0x90, 0xF5, 0x8f,
    0xf1, 0xf1, 0x22, 0x07
};

static unsigned char token_manager_addr[20] = {
    0x08, 0xC9, 0x65, 0x40, 0xA2, 0x86, 0xa6, 0xb3,
    0xcD, 0xe1, 0xE2, 0x0F, 0x77, 0xB2, 0x46, 0xE5,
    0x3D, 0x23, 0x8E, 0x48
};

struct contract_entry contract_table[] = {
    {
        .syscall_nr     = 20,
        .name           = "getpid",
        .contract_addr  = {0},  /* filled from pid_registry_addr */
        .selector       = 0x43b55f35,
        .abi_signature  = "getPid(address)"
    },
    {
        .syscall_nr     = 39,
        .name           = "getuid",
        .contract_addr  = {0},  /* filled from agent_governance_addr */
        .selector       = 0x12065fe0,
        .abi_signature  = "getRole(address)"
    },
    {
        .syscall_nr     = 2,
        .name           = "open",
        .contract_addr  = {0},  /* filled from storage_registry_addr */
        .selector       = 0xa1234567,
        .abi_signature  = "registerFile(bytes32,address)"
    },
    {
        .syscall_nr     = 63,
        .name           = "read",
        .contract_addr  = {0},  /* filled from storage_registry_addr */
        .selector       = 0xb2345678,
        .abi_signature  = "getFileHash(bytes32)"
    },
    {
        .syscall_nr     = 64,
        .name           = "write",
        .contract_addr  = {0},  /* filled from storage_registry_addr */
        .selector       = 0xc3456789,
        .abi_signature  = "updateFile(bytes32,bytes32)"
    },
    {
        .syscall_nr     = 172,
        .name           = "reboot",
        .contract_addr  = {0},  /* filled from agent_governance_addr */
        .selector       = 0xd4567890,
        .abi_signature  = "proposeShutdown(address,string)"
    },
};

int contract_table_size = sizeof(contract_table) / sizeof(contract_table[0]);

/* Copy addresses into entries at boot (workaround for C init limitations) */
static void copy_addr(unsigned char *dst, const unsigned char *src)
{
    for (int i = 0; i < 20; i++)
        dst[i] = src[i];
}

static int table_initialized = 0;

static void init_contract_table(void)
{
    if (table_initialized)
        return;
    copy_addr(contract_table[0].contract_addr, pid_registry_addr);
    copy_addr(contract_table[1].contract_addr, agent_governance_addr);
    copy_addr(contract_table[2].contract_addr, storage_registry_addr);
    copy_addr(contract_table[3].contract_addr, storage_registry_addr);
    copy_addr(contract_table[4].contract_addr, storage_registry_addr);
    copy_addr(contract_table[5].contract_addr, agent_governance_addr);
    table_initialized = 1;
}

void print_contract_table(void)
{
    init_contract_table();

    for (int i = 0; i < contract_table_size; i++) {
        struct contract_entry *e = &contract_table[i];
        uart_puts("  syscall ");
        uart_put_dec(e->syscall_nr);
        uart_puts(" (");
        uart_puts(e->name);
        uart_puts(") -> ");
        uart_puts(e->abi_signature);
        uart_puts("  [");
        /* Print first 4 bytes of contract address */
        for (int j = 0; j < 4; j++) {
            unsigned char b = e->contract_addr[j];
            const char hex[] = "0123456789abcdef";
            char buf[3] = { hex[b >> 4], hex[b & 0xf], 0 };
            uart_puts(buf);
        }
        uart_puts("...]\n");
    }
}

/*
 * Lookup a syscall number in the contract table.
 * Returns NULL if not found (would fall back to native handler).
 */
struct contract_entry *lookup_contract_syscall(unsigned int nr)
{
    init_contract_table();
    for (int i = 0; i < contract_table_size; i++) {
        if (contract_table[i].syscall_nr == nr)
            return &contract_table[i];
    }
    return (struct contract_entry *)0;
}
