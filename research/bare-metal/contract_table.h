/*
 * NEXUS OS Contract Syscall Table — Header
 *
 * Maps traditional syscall numbers to smart contract
 * addresses + function selectors.
 */

#ifndef CONTRACT_TABLE_H
#define CONTRACT_TABLE_H

struct contract_entry {
    unsigned int    syscall_nr;
    const char     *name;
    unsigned char   contract_addr[20];  /* Ethereum address */
    unsigned int    selector;           /* 4-byte function selector */
    const char     *abi_signature;
};

extern struct contract_entry contract_table[];
extern int contract_table_size;

void print_contract_table(void);

#endif /* CONTRACT_TABLE_H */
