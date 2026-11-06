# SPDX-License-Identifier: MIT
"""The T6034 display handoff entry: J514M only, its DCP image pinned, its own PMP values.

Builds kboot_display_handoff.c's SoC table and the opening of dt_set_display_handoff() (the
entry selection and the board gate) with real libfdt, and kboot.c's T6034 PMP values entry.
Each mutation of the entry or of the gate makes a case fail.
"""
from pathlib import Path

import pytest

import subprocess




def build(tmp_path, name, source):
    """Compile only; a mutation must build and then fail when run"""
    binary = tmp_path / name
    lib = ROOT / "src/libfdt"
    subprocess.run(
        ["cc", "-std=gnu11", "-D_GNU_SOURCE", "-Wall", "-Wextra", "-Werror",
         "-Wno-unused-parameter", "-Wno-unused-function", "-I", str(lib), "-x", "c", "-",
         *map(str, (lib / f for f in (
             "fdt.c", "fdt_ro.c", "fdt_rw.c", "fdt_sw.c", "fdt_wip.c",
             "fdt_empty_tree.c", "fdt_strerror.c"))), "-o", str(binary)],
        input=source, text=True, check=True)
    return binary

ROOT = Path(__file__).resolve().parents[2]
HANDOFF = (ROOT / "src/kboot_display_handoff.c").read_text()
KBOOT = (ROOT / "src/kboot.c").read_text()
SOC_H = (ROOT / "src/soc.h").read_text()
FW_H = (ROOT / "src/firmware.h").read_text()


def between(source, start, end):
    a = source.index(start)
    return source[a:source.index(end, a) + len(end)]


def harness(handoff=HANDOFF, kboot=KBOOT):
    chips = "\n".join(l for l in SOC_H.splitlines()
                      if l.startswith("#define T") and l.split()[1].isalnum() and
                      l.split()[2].startswith("0x"))
    tables = between(handoff, "#define DCP6_UUID", "#define DCP6_DART_VM_SIZE 0x1000000000UL")
    tables += "\n#define DCP6_SEGS 8\n"
    tables += "\n".join(l for l in handoff.splitlines() if l.startswith("#define SEG_FLAGS_")) + "\n"
    tables += between(handoff, "struct dcp6_seg_def {", "};")
    tables += "\n" + between(handoff, "static const struct dcp6_seg_def dcp6_seg_defs_t6030[DCP6_SEGS] = {", "\n};")
    tables += "\n" + between(handoff, "static const char *const dcp6_nubs_t6030[]",
                             "static const struct dcp_soc *const dcp_socs[] = {")
    tables += between(handoff[handoff.index("static const struct dcp_soc *const dcp_socs[] = {"):],
                      "{", "};")[1:]
    board_ok = between(handoff, "static bool dcp6_board_ok(void *dt)\n{", "\n}")
    gate = between(handoff, "int dt_set_display_handoff(void *dt)\n{", "bool armed = dcp6_armed(dt);")
    gate = gate.replace("bool armed = dcp6_armed(dt);", "return 1;\n}")
    pmp = between(kboot, "struct pmp_values_soc {", "};") + "\n" + \
        between(kboot, "static const struct pmp_values_soc pmp_values_t6034 = {", "};")
    pmp_pass = between(kboot, "static int dt_set_pmp_t6034(void)\n{", "\n}")
    return r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "libfdt.h"
typedef uint32_t u32;
typedef uint64_t u64;
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define SZ_16K 0x4000UL
#define SZ_1M 0x100000UL
''' + between(FW_H, "enum fw_version {", "};") + "\n" + chips + "\n" + r'''
static u32 chip_id;
static void *the_dt;
struct dcp_soc;
static struct { const struct dcp_soc *soc; } dcp6;
#define dlog(fmt, ...) printf("DCP: %s: " fmt, dcp6.soc->name, ##__VA_ARGS__)
''' + tables.replace("static struct {", "static struct { /* unused */") + "\n" + board_ok + "\n" + \
        gate + "\n" + pmp + r'''
static const struct pmp_values_soc *passed;
static void dt_pass_pmp(const struct pmp_values_soc *v) { passed = v; }
static bool t6034_board(void *dt)
{
    return chip_id == T6034 && !fdt_node_check_compatible(dt, 0, "apple,t6034") &&
           !fdt_node_check_compatible(dt, 0, "apple,j514m");
}
#define dt the_dt
''' + pmp_pass + r'''
#undef dt
static unsigned char blob[4096];
static void *root(const char *board, const char *soc)
{
    char c[64];
    size_t n = strlen(board) + 1, m = strlen(soc) + 1;
    memcpy(c, board, n);
    memcpy(c + n, soc, m);
    assert(!fdt_create_empty_tree(blob, sizeof(blob)));
    assert(!fdt_setprop(blob, 0, "compatible", c, n + m));
    return blob;
}
int main(void)
{
    /* The J514M on a T6034 reaches its own entry, the rest of the handoff runs */
    chip_id = T6034;
    assert(dt_set_display_handoff(root("apple,j514m", "apple,t6034")) == 1);
    const struct dcp_soc *s = dcp6.soc;
    assert(s == &dcp_soc_t6034 && s->chip == T6034 && !strcmp(s->compat, "apple,t6034"));
    assert(s->boards[0] && !strcmp(s->boards[0], "apple,j514m") && !s->boards[1]);
    assert(s->board_gate && !s->always);
    assert(!strcmp(s->dcp_compat, "apple,t6034-dcp"));
    assert(!strcmp(s->disp_compat, "apple,t6034-display-subsystem"));
    assert(!strcmp(s->marker, "apple,t6034-handoff"));
    assert(!strcmp(s->optin, "asahi,t6034-dcp"));
    /* Pinned to the 14.7 DCP image the kernel's J514M record pins, never any image */
    assert(!s->any_uuid && s->uuid && !strcmp(s->uuid, "F493F03E-CC40-3D89-9A08-5F259BA2B246"));
    assert(s->os_fw == V14_7);

    /* The J516M, an unknown board, or the J514M with another chip: nothing at all */
    assert(dt_set_display_handoff(root("apple,j516m", "apple,t6034")) == 0);
    assert(dt_set_display_handoff(root("apple,j999", "apple,t6034")) == 0);
    chip_id = T6031;
    assert(dt_set_display_handoff(root("apple,j514m", "apple,t6034")) == 0);
    chip_id = T6034;

    /* The PMP values go under their own T6034 name, only on the J514M */
    the_dt = root("apple,j514m", "apple,t6034");
    passed = NULL;
    dt_set_pmp_t6034();
    assert(passed == &pmp_values_t6034);
    assert(!strcmp(passed->compat, "apple,t6034") && !strcmp(passed->node, "asahi,t6034-pmp"));
    the_dt = root("apple,j516m", "apple,t6034");
    passed = NULL;
    dt_set_pmp_t6034();
    assert(!passed);
    return 0;
}
'''


def test_the_t6034_handoff_entry_is_the_j514m_s(tmp_path):
    subprocess.run([str(build(tmp_path, "t6034-handoff", harness()))], check=True)


MUTATIONS = {
    "j516m-in-the-boards": ('static const char *const dcp_boards_t6034[] = {"apple,j514m", NULL};',
                            'static const char *const dcp_boards_t6034[] = {"apple,j514m", "apple,j516m", NULL};'),
    "no-board-gate": ('    .boards_desc = "J514M",', '    .boards_desc = "J514M",\n    .board_gate = false,'),
    "any-uuid": ('    .uuid = "F493F03E-CC40-3D89-9A08-5F259BA2B246",', '    .any_uuid = true,'),
    "gate-ignores-chip": ("if (dcp6.soc->board_gate && (chip_id != dcp6.soc->chip || !dcp6_board_ok(dt))) {",
                          "if (dcp6.soc->board_gate && !dcp6_board_ok(dt)) {"),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS) + ["t6031-pmp-name"])
def test_each_mutation_fails(tmp_path, name):
    handoff, kboot = HANDOFF, KBOOT
    if name == "t6031-pmp-name":
        old = '"apple,t6034", "asahi,t6034-pmp", "T6034",'
        assert kboot.count(old) == 1
        kboot = kboot.replace(old, '"apple,t6034", "asahi,t6031-pmp", "T6034",')
    else:
        old, new = MUTATIONS[name]
        assert handoff.count(old) == 1, name
        handoff = handoff.replace(old, new)
        if name == "no-board-gate":
            # a later designated initializer wins: drop the original line instead
            handoff = handoff.replace("    .board_gate = false,", "", 1)
            handoff = handoff.replace("    .adt_psreg = true,\n    .board_gate = true,\n    .uuid = \"F493",
                                      "    .adt_psreg = true,\n    .uuid = \"F493", 1)
    binary = build(tmp_path, name, harness(handoff, kboot))
    assert subprocess.run([str(binary)], capture_output=True).returncode != 0, name
