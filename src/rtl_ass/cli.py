"""Command-line interface for deterministic Codex helpers."""

from __future__ import annotations

import argparse
import json
import sys
from enum import StrEnum
from pathlib import Path
from typing import Any, Sequence

from rtl_ass import __version__
from rtl_ass.compile_manifest import CompileManifest
from rtl_ass.config import Settings, load_settings
from rtl_ass.corpus import audit_corpus, write_manifest_atomic
from rtl_ass.corpus_lock import build_corpus_lock, import_corpus_lock, write_corpus_lock
from rtl_ass.errors import RtlAssError
from rtl_ass.evidence import (
    run_equivalence_evidence,
    run_formal_evidence,
    run_opensta,
    run_simulation_evidence,
    run_verilator_lint,
    run_yosys_synthesis,
)
from rtl_ass.integrity import hash_file, parse_json, read_utf8_exact
from rtl_ass.kb.database import KnowledgeDatabase
from rtl_ass.kb.gates import validate_run_evidence
from rtl_ass.kb.ingest import ingest_path
from rtl_ass.kb.models import LicenseStatus, LinkRelation, ObservationAttribution, RecordRole, RecordStatus
from rtl_ass.kb.packs import load_knowledge_pack, write_knowledge_pack
from rtl_ass.kb.retrieval import build_retrieval_receipt, write_retrieval_receipt
from rtl_ass.project import inspect_project
from rtl_ass.tools import discover_tools
from rtl_ass.waveform import first_divergence_waveform, query_waveform
from rtl_ass.workflow import (
    load_verification_plan,
    summarize_verification_plan,
    verification_execution_lock,
)


def _enum_values(enum_type: type[StrEnum]) -> list[str]:
    return [item.value for item in enum_type]


def _database(path: str) -> KnowledgeDatabase:
    return KnowledgeDatabase(Path(path))


def _load_json_object(path: str) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise RtlAssError("evidence_not_found", "evidence JSON file does not exist", {"path": path})
    try:
        value = parse_json(read_utf8_exact(source))
    except (ValueError, UnicodeDecodeError) as exc:
        raise RtlAssError(
            "invalid_evidence_json", "evidence file must contain one UTF-8 JSON object", {"reason": str(exc)}
        ) from exc
    if not isinstance(value, dict):
        raise RtlAssError("invalid_evidence_json", "evidence JSON root must be an object")
    return value


def _load_json_objects(paths: Sequence[str]) -> list[dict[str, Any]]:
    return [_load_json_object(path) for path in paths]


def _load_utf8_text(path: str, *, max_bytes: int = 2 * 1024 * 1024) -> str:
    source = Path(path)
    if not source.is_file():
        raise RtlAssError("content_not_found", "knowledge content file does not exist", {"path": path})
    if source.stat().st_size > max_bytes:
        raise RtlAssError(
            "content_too_large", "knowledge content exceeds the supported byte limit", {"max_bytes": max_bytes}
        )
    try:
        return read_utf8_exact(source)
    except UnicodeDecodeError as exc:
        raise RtlAssError("invalid_content_encoding", "knowledge content must be UTF-8", {"path": path}) from exc


def build_parser(settings: Settings | None = None) -> argparse.ArgumentParser:
    settings = settings or Settings()
    parser = argparse.ArgumentParser(prog="rtl-ass", description="Open-source RTL support for Codex")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", help="strict UTF-8 TOML configuration file")
    commands = parser.add_subparsers(dest="command", required=True)

    doctor = commands.add_parser("doctor", help="discover optional open-source RTL tools")
    doctor.set_defaults(handler=_handle_doctor)

    inspect = commands.add_parser("inspect", help="inspect RTL sources without executing them")
    inspect.add_argument("path")
    inspect.add_argument("--max-source-bytes", type=int, default=settings.max_source_bytes)
    inspect.add_argument("--follow-symlinks", action=argparse.BooleanOptionalAction, default=settings.follow_symlinks)
    inspect.add_argument("--json", action="store_true", help="retained for explicit machine-readable intent")
    inspect.set_defaults(handler=_handle_inspect)

    manifest = commands.add_parser("manifest", help="validate an audited RTL compile manifest")
    manifest_commands = manifest.add_subparsers(dest="manifest_command", required=True)
    manifest_validate = manifest_commands.add_parser("validate", help="validate and hash a compile manifest")
    manifest_validate.add_argument("path")
    manifest_validate.set_defaults(handler=_handle_manifest_validate)

    corpus = commands.add_parser("corpus", help="audit quarantined open-source corpus checkouts")
    corpus_commands = corpus.add_subparsers(dest="corpus_command", required=True)
    corpus_audit = corpus_commands.add_parser("audit", help="build a pinned source and license manifest")
    corpus_audit.add_argument("path")
    corpus_audit.add_argument("--output")
    corpus_audit.set_defaults(handler=_handle_corpus_audit)
    corpus_lock = corpus_commands.add_parser("lock", help="build a reviewed file-level corpus lock")
    corpus_lock.add_argument("policy")
    corpus_lock.add_argument("--source-root")
    corpus_lock.add_argument("--output", required=True)
    corpus_lock.set_defaults(handler=_handle_corpus_lock)

    verify = commands.add_parser("verify", help="run bounded open-source RTL evidence tools")
    verify_commands = verify.add_subparsers(dest="verify_command", required=True)
    plan = verify_commands.add_parser("plan", help="validate and hash a Codex-selected verification plan")
    plan.add_argument("path")
    plan.set_defaults(handler=_handle_verify_plan)
    summarize = verify_commands.add_parser("summarize", help="revalidate explicitly linked evidence and stopping state")
    summarize.add_argument("--plan", required=True)
    summarize.add_argument("--evidence", action="append", default=[], metavar="CLAIM_ID=PATH")
    summarize.add_argument(
        "--require-ready",
        action="store_true",
        help="return a structured error unless every required claim is satisfied",
    )
    summarize.set_defaults(handler=_handle_verify_summarize)
    lint = verify_commands.add_parser("lint", help="run Verilator lint evidence")
    _add_compile_arguments(lint)
    lint.set_defaults(handler=_handle_verify_lint, requires_eda_lock=True)
    simulate = verify_commands.add_parser("simulate", help="compile and run with Icarus Verilog or Verilator")
    _add_compile_arguments(simulate)
    simulate.add_argument("--backend", choices=("iverilog", "verilator"), default="iverilog")
    simulate.set_defaults(handler=_handle_verify_simulate, requires_eda_lock=True)
    synthesize = verify_commands.add_parser("synth", help="run generic Yosys synthesis evidence")
    _add_compile_arguments(synthesize, default_timeout=120)
    synthesize.add_argument("--liberty", help="map to this exact Liberty library and emit a Verilog netlist")
    synthesize.set_defaults(handler=_handle_verify_synth, requires_eda_lock=True)
    formal = verify_commands.add_parser("formal", help="run bounded Yosys assertion evidence")
    _add_compile_arguments(formal, default_timeout=120)
    formal.add_argument("--depth", type=int, default=20, help="bounded time steps (1-1000)")
    formal.add_argument(
        "--initialization",
        choices=("defined", "zero"),
        default="defined",
        help="initial state: arbitrary defined bits or all zero",
    )
    formal.add_argument("--backend", choices=("yosys", "sby"), default="yosys")
    formal.add_argument("--solver", choices=("bitwuzla", "boolector", "cvc5", "yices", "z3"), default="z3")
    formal.set_defaults(handler=_handle_verify_formal, requires_eda_lock=True)
    equivalence = verify_commands.add_parser("equiv", help="run Yosys combinational or bounded equivalence evidence")
    equivalence.add_argument("--reference-source", action="append")
    equivalence.add_argument("--implementation-source", action="append")
    equivalence.add_argument("--reference-top")
    equivalence.add_argument("--implementation-top")
    equivalence.add_argument("--reference-manifest")
    equivalence.add_argument("--implementation-manifest")
    _add_compile_option_arguments(equivalence)
    equivalence.add_argument(
        "--depth", type=int, default=1, help="1 for combinational; larger values are bounded-sequential"
    )
    equivalence.add_argument(
        "--input-domain",
        choices=("defined", "undefined"),
        default="defined",
        help="prove ordinary defined-bit behavior or also model undefined states",
    )
    equivalence.add_argument(
        "--initialization",
        choices=("none", "zero"),
        default="none",
        help="none for combinational checks; zero preserves source init values and defaults other state to zero",
    )
    equivalence.add_argument("--artifact-dir", required=True)
    equivalence.add_argument("--timeout", type=int, default=120)
    _add_lock_argument(equivalence)
    equivalence.add_argument("--backend", choices=("yosys", "eqy"), default="yosys")
    equivalence.add_argument("--solver", choices=("bitwuzla", "boolector", "cvc5", "yices", "z3"), default="z3")
    equivalence.set_defaults(handler=_handle_verify_equivalence, requires_eda_lock=True)
    sta = verify_commands.add_parser("sta", help="run OpenSTA with an exact netlist, Liberty, and SDC")
    sta_input = sta.add_mutually_exclusive_group(required=True)
    sta_input.add_argument("--netlist")
    sta_input.add_argument("--synthesis-evidence", help="validated mapped-synthesis evidence containing netlist.v")
    sta.add_argument("--liberty", required=True)
    sta.add_argument("--constraints", required=True)
    sta.add_argument("--top", required=True)
    sta.add_argument("--artifact-dir", required=True)
    sta.add_argument("--timeout", type=int, default=120)
    _add_lock_argument(sta)
    sta.set_defaults(handler=_handle_verify_sta, requires_eda_lock=True)

    wave = commands.add_parser("wave", help="query real VCD or FST waveform evidence")
    wave_commands = wave.add_subparsers(dest="wave_command", required=True)
    wave_query = wave_commands.add_parser("query", help="return bounded VCD or FST signal events")
    wave_query.add_argument("path")
    wave_query.add_argument("--signal", action="append", required=True)
    _add_wave_window_arguments(wave_query)
    _add_lock_argument(wave_query)
    wave_query.set_defaults(handler=_handle_wave_query, requires_eda_lock=True)
    wave_diff = wave_commands.add_parser("diff", help="find the first VCD or FST divergence after same-time updates")
    wave_diff.add_argument("path")
    wave_diff.add_argument("--expected", required=True)
    wave_diff.add_argument("--actual", required=True)
    _add_wave_window_arguments(wave_diff, default_max_events=100_000)
    _add_lock_argument(wave_diff)
    wave_diff.set_defaults(handler=_handle_wave_diff, requires_eda_lock=True)

    kb = commands.add_parser("kb", help="manage the audited local RTL knowledge index")
    kb_commands = kb.add_subparsers(dest="kb_command", required=True)

    init = kb_commands.add_parser("init", help="initialize a knowledge database")
    _add_database_argument(init, settings)
    init.add_argument("--actor", default="rtl-ass")
    init.set_defaults(handler=_handle_kb_init)

    migrate = kb_commands.add_parser("migrate", help="run an explicit verified database schema migration")
    _add_database_argument(migrate, settings)
    migrate.add_argument("--actor", required=True)
    migrate.set_defaults(handler=_handle_kb_migrate)

    ingest = kb_commands.add_parser("ingest", help="ingest RTL/TB source as untrusted knowledge")
    ingest.add_argument("path")
    _add_database_argument(ingest, settings)
    ingest.add_argument("--namespace", default=settings.default_namespace)
    ingest.add_argument("--actor", default="rtl-ass")
    ingest.add_argument("--role", choices=_enum_values(RecordRole))
    ingest.add_argument("--source-uri", default="")
    ingest.add_argument("--source-revision", default="")
    ingest.add_argument("--license-spdx", default="UNKNOWN")
    ingest.add_argument("--license-status", choices=_enum_values(LicenseStatus), default=LicenseStatus.UNKNOWN.value)
    ingest.add_argument(
        "--initial-status",
        choices=[RecordStatus.RAW.value, RecordStatus.CANDIDATE.value],
        default=RecordStatus.RAW.value,
    )
    ingest.add_argument("--max-source-bytes", type=int, default=settings.max_source_bytes)
    ingest.set_defaults(handler=_handle_kb_ingest)

    import_corpus = kb_commands.add_parser("import-corpus", help="atomically import a reviewed corpus lock")
    import_corpus.add_argument("lock")
    import_corpus.add_argument("--source-root", required=True)
    _add_database_argument(import_corpus, settings)
    import_corpus.add_argument("--actor", required=True)
    import_corpus.set_defaults(handler=_handle_kb_import_corpus)

    stats = kb_commands.add_parser("stats", help="report audited knowledge inventory counts")
    _add_database_argument(stats, settings)
    stats.set_defaults(handler=_handle_kb_stats)

    search = kb_commands.add_parser("search", help="search explicit knowledge namespaces")
    search.add_argument("query")
    _add_database_argument(search, settings)
    search.add_argument("--namespace", action="append", required=True)
    search.add_argument("--limit", type=int, default=settings.search_limit)
    search.add_argument("--role", choices=_enum_values(RecordRole))
    search.add_argument("--status", choices=_enum_values(RecordStatus))
    search.add_argument(
        "--match",
        choices=("all", "any"),
        default="all",
        help="require every query token or rank records matching any token",
    )
    search.add_argument("--actor", default="rtl-ass")
    search.add_argument("--output", help="write an immutable retrieval receipt for workflow auditing")
    search.set_defaults(handler=_handle_kb_search)

    show = kb_commands.add_parser("show", help="show one knowledge record")
    show.add_argument("record_id")
    _add_database_argument(show, settings)
    show.add_argument("--include-content", action="store_true")
    show.set_defaults(handler=_handle_kb_show)

    derive = kb_commands.add_parser("derive", help="create a candidate distilled record linked to its exact source")
    derive.add_argument("source_record_id")
    _add_database_argument(derive, settings)
    derive.add_argument("--namespace", required=True)
    derive.add_argument("--actor", required=True)
    derive.add_argument(
        "--role",
        choices=[role.value for role in RecordRole if role is not RecordRole.TOOL_EVIDENCE],
        required=True,
    )
    derive.add_argument("--language", required=True)
    derive.add_argument("--title", required=True)
    derive.add_argument("--summary", required=True)
    derive.add_argument("--content-file", required=True)
    derive.add_argument("--source-path", required=True)
    derive.add_argument(
        "--method",
        choices=("extract", "generalize", "normalize", "repair", "summarize"),
        required=True,
    )
    derive.set_defaults(handler=_handle_kb_derive)

    pack_validate = kb_commands.add_parser("pack-validate", help="validate a portable knowledge-pack contract")
    pack_validate.add_argument("path")
    pack_validate.set_defaults(handler=_handle_kb_pack_validate)

    pack_import = kb_commands.add_parser("import-pack", help="atomically import a validated pack as raw knowledge")
    pack_import.add_argument("path")
    _add_database_argument(pack_import, settings)
    pack_import.add_argument("--namespace", required=True)
    pack_import.add_argument("--actor", required=True)
    pack_import.set_defaults(handler=_handle_kb_import_pack)

    pack_export = kb_commands.add_parser("export-pack", help="export explicit records with known license metadata")
    _add_database_argument(pack_export, settings)
    pack_export.add_argument("--record", action="append", required=True)
    pack_export.add_argument("--name", required=True)
    pack_export.add_argument("--pack-version", required=True)
    pack_export.add_argument("--description", required=True)
    pack_export.add_argument("--license-spdx", required=True)
    pack_export.add_argument("--output", required=True)
    pack_export.set_defaults(handler=_handle_kb_export_pack)

    transition = kb_commands.add_parser("transition", help="perform one guarded lifecycle transition")
    transition.add_argument("record_id")
    transition.add_argument("target", choices=_enum_values(RecordStatus))
    _add_database_argument(transition, settings)
    transition.add_argument("--actor", required=True)
    transition.set_defaults(handler=_handle_kb_transition)

    verify_record = kb_commands.add_parser("verify", help="atomically record passing evidence and verify one candidate")
    verify_record.add_argument("record_id")
    _add_database_argument(verify_record, settings)
    verify_record.add_argument("--actor", required=True)
    verify_record.add_argument("--evidence-json", action="append", required=True)
    verify_record.set_defaults(handler=_handle_kb_verify, settings=settings)

    observe = kb_commands.add_parser("observe", help="atomically retain non-passing evidence with explicit attribution")
    observe.add_argument("record_id")
    _add_database_argument(observe, settings)
    observe.add_argument("--actor", required=True)
    observe.add_argument("--attribution", choices=_enum_values(ObservationAttribution), required=True)
    observe.add_argument("--evidence-json", action="append", required=True)
    observe.set_defaults(handler=_handle_kb_observe)

    link = kb_commands.add_parser("link", help="link exact RTL, TB, assertion, model, or evidence records")
    _add_database_argument(link, settings)
    link.add_argument("--source", required=True)
    link.add_argument("--target", required=True)
    link.add_argument("--relation", choices=_enum_values(LinkRelation), required=True)
    link.add_argument("--actor", required=True)
    link.set_defaults(handler=_handle_kb_link)

    links = kb_commands.add_parser("links", help="list exact relationships for one knowledge record")
    links.add_argument("record_id")
    _add_database_argument(links, settings)
    links.set_defaults(handler=_handle_kb_links)

    audit = kb_commands.add_parser("audit", help="read append-only audit events")
    _add_database_argument(audit, settings)
    audit.add_argument("--limit", type=int, default=50)
    audit.set_defaults(handler=_handle_kb_audit)
    return parser


def _add_database_argument(parser: argparse.ArgumentParser, settings: Settings) -> None:
    parser.add_argument("--db", default=str(settings.database))


def _add_compile_option_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--language", choices=("systemverilog", "verilog-2005"))
    parser.add_argument("--include-dir", action="append")
    parser.add_argument("--library-file", action="append")
    parser.add_argument("--define", action="append")
    parser.add_argument("--parameter", action="append")


def _add_compile_arguments(parser: argparse.ArgumentParser, *, default_timeout: int = 60) -> None:
    parser.add_argument("--manifest")
    parser.add_argument("--source", action="append")
    parser.add_argument("--top")
    _add_compile_option_arguments(parser)
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--timeout", type=int, default=default_timeout)
    _add_lock_argument(parser)


def _add_lock_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--lock-timeout",
        type=int,
        default=30,
        help="seconds to wait for the one-per-workspace EDA execution lock",
    )


def _add_wave_window_arguments(parser: argparse.ArgumentParser, *, default_max_events: int = 1000) -> None:
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int)
    parser.add_argument("--max-events", type=int, default=default_max_events)
    parser.add_argument("--conversion-timeout", type=int, default=60, help="FST-to-VCD conversion timeout")
    parser.add_argument(
        "--max-converted-bytes",
        type=int,
        default=256 * 1024 * 1024,
        help="maximum temporary VCD bytes produced from FST",
    )


def _handle_doctor(_args: argparse.Namespace) -> dict[str, Any]:
    return discover_tools()


def _handle_inspect(args: argparse.Namespace) -> dict[str, Any]:
    return inspect_project(
        args.path,
        max_source_bytes=args.max_source_bytes,
        follow_symlinks=args.follow_symlinks,
    )


def _handle_manifest_validate(args: argparse.Namespace) -> dict[str, Any]:
    return CompileManifest.load(args.path).summary()


def _handle_verify_plan(args: argparse.Namespace) -> dict[str, Any]:
    return load_verification_plan(args.path).summary()


def _handle_verify_summarize(args: argparse.Namespace) -> dict[str, Any]:
    summary = summarize_verification_plan(load_verification_plan(args.plan), args.evidence)
    if args.require_ready and not summary["ready_to_stop"]:
        raise RtlAssError(
            "verification_plan_unsatisfied",
            "required verification claims are not yet satisfied",
            {
                "plan_id": summary["plan_id"],
                "plan_hash": summary["plan_hash"],
                "missing_required_claims": summary["missing_required_claims"],
                "unsatisfied_required_claims": summary["unsatisfied_required_claims"],
            },
        )
    return summary


def _handle_corpus_audit(args: argparse.Namespace) -> dict[str, Any]:
    manifest = audit_corpus(args.path)
    if args.output:
        destination = write_manifest_atomic(manifest, args.output)
        return {
            "schema_version": "1.0",
            "source_count": manifest["source_count"],
            "manifest": destination.as_posix(),
        }
    return manifest


def _handle_corpus_lock(args: argparse.Namespace) -> dict[str, Any]:
    lock = build_corpus_lock(args.policy, source_root=args.source_root)
    destination = write_corpus_lock(lock, args.output)
    return {
        "schema_version": "1.0",
        "lock": destination.as_posix(),
        "lock_hash": lock["lock_hash"],
        "repository_count": lock["repository_count"],
        "file_count": lock["file_count"],
        "byte_count": lock["byte_count"],
    }


def _handle_verify_lint(args: argparse.Namespace) -> dict[str, Any]:
    return run_verilator_lint(
        _compile_manifest_from_args(args),
        artifact_root=args.artifact_dir,
        timeout_seconds=args.timeout,
    )


def _handle_verify_simulate(args: argparse.Namespace) -> dict[str, Any]:
    return run_simulation_evidence(
        _compile_manifest_from_args(args),
        backend=args.backend,
        artifact_root=args.artifact_dir,
        timeout_seconds=args.timeout,
    )


def _handle_verify_synth(args: argparse.Namespace) -> dict[str, Any]:
    return run_yosys_synthesis(
        _compile_manifest_from_args(args),
        liberty=args.liberty,
        artifact_root=args.artifact_dir,
        timeout_seconds=args.timeout,
    )


def _handle_verify_formal(args: argparse.Namespace) -> dict[str, Any]:
    return run_formal_evidence(
        _compile_manifest_from_args(args),
        backend=args.backend,
        depth=args.depth,
        initialization=args.initialization,
        artifact_root=args.artifact_dir,
        timeout_seconds=args.timeout,
        solver=args.solver,
    )


def _handle_verify_equivalence(args: argparse.Namespace) -> dict[str, Any]:
    reference, implementation = _equivalence_manifests_from_args(args)
    return run_equivalence_evidence(
        reference_sources=reference,
        implementation_sources=implementation,
        backend=args.backend,
        depth=args.depth,
        input_domain=args.input_domain,
        initialization=args.initialization,
        artifact_root=args.artifact_dir,
        timeout_seconds=args.timeout,
        solver=args.solver,
    )


def _compile_manifest_from_args(args: argparse.Namespace) -> CompileManifest:
    inline_values = (
        args.source,
        args.top,
        args.language,
        args.include_dir,
        args.library_file,
        args.define,
        args.parameter,
    )
    if args.manifest:
        if any(value for value in inline_values):
            raise RtlAssError(
                "conflicting_compile_inputs",
                "--manifest cannot be combined with inline source, top, language, include, library, define, or parameter options",
            )
        return CompileManifest.load(args.manifest)
    if not args.source or not args.top:
        raise RtlAssError("compile_inputs_required", "provide --manifest or both --source and --top")
    return CompileManifest.create(
        args.source,
        args.top,
        language=args.language or "systemverilog",
        include_dirs=args.include_dir or (),
        library_files=args.library_file or (),
        defines=args.define or (),
        parameters=args.parameter or (),
    )


def _equivalence_manifests_from_args(args: argparse.Namespace) -> tuple[CompileManifest, CompileManifest]:
    manifest_mode = bool(args.reference_manifest or args.implementation_manifest)
    inline_options = (args.language, args.include_dir, args.library_file, args.define, args.parameter)
    inline_design = (args.reference_source, args.implementation_source, args.reference_top, args.implementation_top)
    if manifest_mode:
        if not args.reference_manifest or not args.implementation_manifest or any(inline_design) or any(inline_options):
            raise RtlAssError(
                "conflicting_compile_inputs",
                "equivalence requires exactly two manifests or complete inline reference/implementation inputs",
            )
        return CompileManifest.load(args.reference_manifest), CompileManifest.load(args.implementation_manifest)
    if not all(inline_design):
        raise RtlAssError(
            "compile_inputs_required",
            "inline equivalence requires reference/implementation sources and tops",
        )
    return (
        CompileManifest.create(
            args.reference_source,
            args.reference_top,
            language=args.language or "systemverilog",
            include_dirs=args.include_dir or (),
            library_files=args.library_file or (),
            defines=args.define or (),
            parameters=args.parameter or (),
        ),
        CompileManifest.create(
            args.implementation_source,
            args.implementation_top,
            language=args.language or "systemverilog",
            include_dirs=args.include_dir or (),
            library_files=args.library_file or (),
            defines=args.define or (),
            parameters=args.parameter or (),
        ),
    )


def _handle_verify_sta(args: argparse.Namespace) -> dict[str, Any]:
    netlist = args.netlist
    if args.synthesis_evidence is not None:
        netlist = _mapped_netlist_from_evidence(
            args.synthesis_evidence,
            liberty=args.liberty,
            top=args.top,
        )
    return run_opensta(
        netlist=netlist,
        liberty=args.liberty,
        constraints=args.constraints,
        top=args.top,
        artifact_root=args.artifact_dir,
        timeout_seconds=args.timeout,
    )


def _mapped_netlist_from_evidence(path: str, *, liberty: str, top: str) -> str:
    liberty_path = Path(liberty)
    if not liberty_path.is_file() or liberty_path.is_symlink():
        raise RtlAssError(
            "invalid_sta_input",
            "synthesis-linked STA requires the same regular non-symlink Liberty file",
            {"path": liberty},
        )
    evidence = validate_run_evidence(
        _load_json_object(path),
        expected_content_hashes=(hash_file(liberty_path),),
        require_current_artifacts=True,
    )
    compile_summary = evidence["summary"].get("compile_manifest")
    if (
        evidence["kind"] != "synthesis"
        or evidence.get("top") != top
        or not isinstance(compile_summary, dict)
        or compile_summary.get("synthesis_mode") != "liberty-mapped"
    ):
        raise RtlAssError(
            "invalid_synthesis_evidence",
            "STA linkage requires passing Liberty-mapped synthesis evidence for the same top",
        )
    netlists = [
        artifact
        for artifact in evidence["artifacts"]
        if isinstance(artifact, str) and Path(artifact).name == "netlist.v"
    ]
    if len(netlists) != 1:
        raise RtlAssError(
            "invalid_synthesis_evidence",
            "mapped synthesis evidence must contain exactly one netlist.v artifact",
            {"count": len(netlists)},
        )
    return netlists[0]


def _handle_wave_query(args: argparse.Namespace) -> dict[str, Any]:
    return query_waveform(
        args.path,
        patterns=args.signal,
        start_time=args.start,
        end_time=args.end,
        max_events=args.max_events,
        conversion_timeout_seconds=args.conversion_timeout,
        max_converted_bytes=args.max_converted_bytes,
    )


def _handle_wave_diff(args: argparse.Namespace) -> dict[str, Any]:
    return first_divergence_waveform(
        args.path,
        expected=args.expected,
        actual=args.actual,
        start_time=args.start,
        end_time=args.end,
        max_events=args.max_events,
        conversion_timeout_seconds=args.conversion_timeout,
        max_converted_bytes=args.max_converted_bytes,
    )


def _handle_kb_init(args: argparse.Namespace) -> dict[str, Any]:
    return _database(args.db).initialize(actor=args.actor)


def _handle_kb_migrate(args: argparse.Namespace) -> dict[str, Any]:
    return _database(args.db).migrate(actor=args.actor)


def _handle_kb_ingest(args: argparse.Namespace) -> dict[str, Any]:
    return ingest_path(
        _database(args.db),
        args.path,
        namespace=args.namespace,
        actor=args.actor,
        role_override=RecordRole(args.role) if args.role else None,
        source_uri=args.source_uri,
        source_revision=args.source_revision,
        license_spdx=args.license_spdx,
        license_status=LicenseStatus(args.license_status),
        initial_status=RecordStatus(args.initial_status),
        max_source_bytes=args.max_source_bytes,
    )


def _handle_kb_import_corpus(args: argparse.Namespace) -> dict[str, Any]:
    return import_corpus_lock(
        _database(args.db),
        args.lock,
        source_root=args.source_root,
        actor=args.actor,
    )


def _handle_kb_stats(args: argparse.Namespace) -> dict[str, Any]:
    return _database(args.db).statistics()


def _handle_kb_search(args: argparse.Namespace) -> dict[str, Any]:
    results = _database(args.db).search(
        args.query,
        namespaces=args.namespace,
        limit=args.limit,
        role=RecordRole(args.role) if args.role else None,
        status=RecordStatus(args.status) if args.status else None,
        match_mode=args.match,
    )
    if not args.output:
        return {"schema_version": "1.0", "count": len(results), "results": results}
    receipt = build_retrieval_receipt(
        results,
        actor=args.actor,
        query=args.query,
        namespaces=args.namespace,
        limit=args.limit,
        role=args.role,
        status=args.status,
        match_mode=args.match,
    )
    write_retrieval_receipt(receipt, args.output)
    return receipt


def _handle_kb_show(args: argparse.Namespace) -> dict[str, Any]:
    return _database(args.db).get_record(args.record_id, include_content=args.include_content)


def _handle_kb_derive(args: argparse.Namespace) -> dict[str, Any]:
    return _database(args.db).derive_record(
        args.source_record_id,
        namespace=args.namespace,
        role=RecordRole(args.role),
        language=args.language,
        title=args.title,
        summary=args.summary,
        content=_load_utf8_text(args.content_file),
        source_path=args.source_path,
        method=args.method,
        actor=args.actor,
    )


def _handle_kb_pack_validate(args: argparse.Namespace) -> dict[str, Any]:
    pack = load_knowledge_pack(args.path)
    return {
        "schema_version": "1.0",
        "name": pack["name"],
        "version": pack["version"],
        "pack_hash": pack["pack_hash"],
        "record_count": len(pack["records"]),
        "link_count": len(pack["links"]),
    }


def _handle_kb_import_pack(args: argparse.Namespace) -> dict[str, Any]:
    return _database(args.db).import_pack(args.path, namespace=args.namespace, actor=args.actor)


def _handle_kb_export_pack(args: argparse.Namespace) -> dict[str, Any]:
    pack = _database(args.db).export_pack(
        args.record,
        name=args.name,
        version=args.pack_version,
        description=args.description,
        license_spdx=args.license_spdx,
    )
    destination = write_knowledge_pack(pack, args.output)
    return {
        "schema_version": "1.0",
        "output": destination.as_posix(),
        "pack_hash": pack["pack_hash"],
        "record_count": len(pack["records"]),
        "link_count": len(pack["links"]),
    }


def _handle_kb_transition(args: argparse.Namespace) -> dict[str, Any]:
    return _database(args.db).transition(
        args.record_id,
        RecordStatus(args.target),
        actor=args.actor,
    )


def _handle_kb_verify(args: argparse.Namespace) -> dict[str, Any]:
    database = _database(args.db)
    record = database.get_record(args.record_id)
    requirements = args.settings.required_evidence_kinds(RecordRole(record["role"]))
    return database.verify_record(
        args.record_id,
        _load_json_objects(args.evidence_json),
        actor=args.actor,
        required_evidence_kinds=requirements,
    )


def _handle_kb_observe(args: argparse.Namespace) -> dict[str, Any]:
    return _database(args.db).record_observations(
        args.record_id,
        _load_json_objects(args.evidence_json),
        actor=args.actor,
        attribution=ObservationAttribution(args.attribution),
    )


def _handle_kb_link(args: argparse.Namespace) -> dict[str, Any]:
    return _database(args.db).add_link(
        args.source,
        args.target,
        LinkRelation(args.relation),
        actor=args.actor,
    )


def _handle_kb_links(args: argparse.Namespace) -> dict[str, Any]:
    links = _database(args.db).list_links(args.record_id)
    return {"schema_version": "1.0", "record_id": args.record_id, "count": len(links), "links": links}


def _handle_kb_audit(args: argparse.Namespace) -> dict[str, Any]:
    database = _database(args.db)
    events = database.list_audit(limit=args.limit)
    return {
        "schema_version": "1.0",
        "count": len(events),
        "chain": database.verify_audit_chain(),
        "events": events,
    }


def main(argv: Sequence[str] | None = None) -> int:
    preliminary = argparse.ArgumentParser(add_help=False)
    preliminary.add_argument("--config")
    preliminary_args, _ = preliminary.parse_known_args(argv)
    try:
        settings = load_settings(preliminary_args.config)
    except RtlAssError as exc:
        print(json.dumps(exc.to_dict(), ensure_ascii=False, sort_keys=True, indent=2), file=sys.stderr)
        return 2
    parser = build_parser(settings)
    args = parser.parse_args(argv)
    try:
        if getattr(args, "requires_eda_lock", False):
            with verification_execution_lock(args.lock_timeout):
                output = args.handler(args)
        else:
            output = args.handler(args)
    except RtlAssError as exc:
        print(json.dumps(exc.to_dict(), ensure_ascii=False, sort_keys=True, indent=2), file=sys.stderr)
        return 2
    except OSError as exc:
        error = RtlAssError(
            "io_error",
            "the operating system rejected an RTL-ASS file or process operation",
            {"errno": exc.errno, "reason": str(exc)},
        )
        print(json.dumps(error.to_dict(), ensure_ascii=False, sort_keys=True, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2))
    return 0
