"""
Reads a SHACL validation report (e.g. from GraphDB's /validate endpoint or exported
by pyshacl) and writes a clear summary into a
separate CSV file: which entity caused which warning, and which
ContextRequirement is violated/not fulfilled by it.

Usage (default paths: reports/shacl_report.csv of the only open crate as input,
SHACL_REPORT_SUMMARIZED as output):
    python generator/workflow/summarize_shacl_report.py
    python generator/workflow/summarize_shacl_report.py other_report.ttl --output other_file.csv

The requirement is assigned first via sh:sourceShape, if that is a
named MainShape with hlo:isShapeOfRequirement. For anonymous (blank node)
sourceShapes it is assigned via the message text: the script builds from
ContextRequirementShapes.ttl a table "message text -> requirement ID" and
looks up for every result in the report which requirement the message
belongs to (for messages shortened by GraphDB with "..." by prefix). Shapes without
a requirement (DataQualityShapes.ttl) appear, as in generator/workflow/run_shacl.py, under
their own name; assigned via the path.
"""

import argparse
import csv
import sys
from pathlib import Path

# The script lies in generator/workflow/, path_definitions.py one level higher -
# so add the parent folder to the search path explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import path_definitions

try:
    from rdflib import Graph, Namespace, RDF
except ImportError:
    Graph = None


SH = Namespace("http://www.w3.org/ns/shacl#")
HLO = Namespace("http://www.semanticweb.org/lf576/ontologies/2026/7/HigherLevelOntology#")
SCHEMA = Namespace("http://schema.org/")

# Covers all ways in which an sh:message in our shapes can hang at a MainShape with
# hlo:isShapeOfRequirement (directly, via sh:property, or nested in sh:or/sh:and lists
# or sh:not).
MESSAGE_PATH_QUERY = """
PREFIX sh: <http://www.w3.org/ns/shacl#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
SELECT ?message WHERE {
    ?main_shape (sh:property|sh:not|sh:qualifiedValueShape|sh:node
                 |sh:or/rdf:rest*/rdf:first
                 |sh:and/rdf:rest*/rdf:first)* ?shape .
    ?shape sh:message ?message .
}
"""


def build_message_to_requirement_map(shapes_graph, ontology_graph=None):
    """Builds a dict: message text (str) -> (requirement ID, requirement description)."""

    mapping = {}
    for main_shape, requirement in shapes_graph.subject_objects(HLO.isShapeOfRequirement):
        requirement_id = shapes_graph.qname(requirement)

        description = None
        if ontology_graph is not None:
            description = ontology_graph.value(requirement, SCHEMA.description)
            description = str(description) if description is not None else None

        bindings = shapes_graph.query(MESSAGE_PATH_QUERY, initBindings={"main_shape": main_shape})
        for row in bindings:
            mapping[str(row.message)] = (requirement_id, description)

    return mapping


def build_shape_to_requirement_map(shapes_graph, ontology_graph=None):
    """Builds a dict: MainShape IRI -> (requirement ID, requirement description)."""

    mapping = {}
    for main_shape, requirement in shapes_graph.subject_objects(HLO.isShapeOfRequirement):
        description = None
        if ontology_graph is not None:
            description = ontology_graph.value(requirement, SCHEMA.description)
            description = str(description) if description is not None else None
        mapping[main_shape] = (shapes_graph.qname(requirement), description)
    return mapping


SH_TARGETS = (SH.targetClass, SH.targetSubjectsOf, SH.targetObjectsOf, SH.targetNode)


def build_path_to_plain_shape_map(shapes_graph):
    """Builds a dict: sh:path -> (shape name, sh:message) for shapes without a requirement.

    These are the shapes of DataQualityShapes.ttl. They run, as in generator/workflow/run_shacl.py,
    under their own name. Their property shapes are blank nodes without an sh:message
    of their own, the report then names only a generic message - so they are assigned
    via the path. A path used by several such shapes is left out.
    """

    mapping = {}
    ambiguous = set()
    for target in SH_TARGETS:
        for main_shape in set(shapes_graph.subjects(target, None)):
            if (main_shape, HLO.isShapeOfRequirement, None) in shapes_graph:
                continue
            message = shapes_graph.value(main_shape, SH.message)
            value = (shapes_graph.qname(main_shape), str(message) if message is not None else None)
            for property_shape in shapes_graph.objects(main_shape, SH.property):
                path = shapes_graph.value(property_shape, SH.path)
                if path is None:
                    continue
                if path in mapping and mapping[path] != value:
                    ambiguous.add(path)
                mapping[path] = value
    for path in ambiguous:
        del mapping[path]
    return mapping


def lookup_requirement(source_shape, message, shape_to_requirement, message_to_requirement,
                       result_path=None, path_to_plain_shape=None):
    """Finds the requirement of a result.

    Order: 1) named sh:sourceShape, 2) exact message text,
    3) prefix comparison for messages shortened by GraphDB with "...",
    4) path of a shape without a requirement (DataQualityShapes.ttl), under its name.
    """

    if source_shape in shape_to_requirement:
        return shape_to_requirement[source_shape]

    message_text = str(message) if message is not None else ""
    if message_text in message_to_requirement:
        return message_to_requirement[message_text]

    if message_text.endswith(TRUNCATION_MARKER):
        prefix = message_text[:-len(TRUNCATION_MARKER)]
        candidates = {value for text, value in message_to_requirement.items() if text.startswith(prefix)}
        # Take only unambiguous hits, otherwise rather "not assigned".
        if len(candidates) == 1:
            return candidates.pop()

    if path_to_plain_shape and result_path in path_to_plain_shape:
        return path_to_plain_shape[result_path]

    return (None, None)


# Extension -> rdflib format. Everything unknown (e.g. a .csv file with a raw GraphDB
# report) falls back to Turtle, which GraphDB uses for SHACL reports.
_FORMAT_BY_SUFFIX = {
    ".ttl": "turtle",
    ".n3": "n3",
    ".nt": "nt",
    ".rdf": "xml",
    ".owl": "xml",
    ".xml": "xml",
    ".jsonld": "json-ld",
    ".json": "json-ld",
}


def guess_format(path):
    return _FORMAT_BY_SUFFIX.get(Path(path).suffix.lower(), "turtle")


def strip_non_turtle_preamble(text):
    """Cuts away text before the actual RDF content.

    If GraphDB refuses a SHACL validation, it puts a Java exception line in front of
    the report ("org.eclipse.rdf4j.sail.shacl.GraphDBShaclSail
    ValidationException: Failed SHACL validation") - that is no valid
    Turtle and otherwise makes the parser crash with "Prefix ... not bound".
    Everything before the first "@prefix" is dropped, if there is text before it.
    """

    marker = "@prefix"
    index = text.find(marker)
    if index > 0:
        return text[index:]
    return text


TRUNCATION_MARKER = "..."


def repair_truncated_literals(text):
    """Closes string literals cut off by GraphDB again.

    GraphDB shortens long literals in the exception output to about 150 characters
    and appends "..." - without a closing quotation mark. That breaks the
    Turtle-Parser ("newline found in string literal"). Betroffene Zeilen enden
    with "..." and an odd number of quotation marks; there '" ;' is added
    (with GraphDB the following line is always another predicate of the same
    subject). Returns the repaired text and the number of repaired lines.
    """

    repaired_lines = []
    repaired_count = 0
    for line in text.split("\n"):
        stripped = line.rstrip()
        unescaped_quotes = stripped.count('"') - stripped.count('\\"')
        if stripped.endswith(TRUNCATION_MARKER) and unescaped_quotes % 2 == 1:
            line = stripped + '" ;'
            repaired_count += 1
        repaired_lines.append(line)
    return "\n".join(repaired_lines), repaired_count


def parse_graph(path):
    """Loads an RDF file robustly.

    Reads the file itself as text and passes the content to rdflib directly
    (instead of a path string) - otherwise rdflib takes a Windows path such as
    "C:\\..." wrongly for a URL with the scheme "c" (URLError: unknown url
    type: c). Also cuts away a GraphDB exception line, if any, before
    the actual Turtle content (see strip_non_turtle_preamble).
    """

    graph = Graph()
    file_path = Path(path).resolve()
    guessed_format = guess_format(file_path)
    raw_text = strip_non_turtle_preamble(file_path.read_text(encoding="utf-8", errors="replace"))
    if guessed_format == "turtle":
        raw_text, repaired_count = repair_truncated_literals(raw_text)
        if repaired_count:
            print(f"Note: {repaired_count} literals cut off in '{file_path.name}' repaired "
                  "(GraphDB shortens long messages with '...').")

    try:
        graph.parse(data=raw_text, format=guessed_format, publicID=file_path.as_uri())
    except Exception:
        if guessed_format == "turtle":
            raise
        graph.parse(data=raw_text, format="turtle", publicID=file_path.as_uri())
    return graph


def summarize(report_path, shapes_paths, ontology_path, output_path):
    if Graph is None:
        print("Note: rdflib is not installed (pip install rdflib). Stopping.")
        return

    report_graph = parse_graph(report_path)
    shapes_graph = Graph()
    for shapes_path in shapes_paths:
        parsed = parse_graph(shapes_path)
        # += takes over only the triples; without the prefixes hlo: would be called ns1: in the output.
        for prefix, namespace in parsed.namespaces():
            shapes_graph.bind(prefix, namespace, override=False)
        shapes_graph += parsed

    ontology_graph = None
    if ontology_path is not None:
        try:
            ontology_graph = parse_graph(ontology_path)
        except Exception as error:
            print(f"Note: ontology file '{ontology_path}' could not be loaded ({error}). "
                  "The requirement descriptions are then missing from the output.")

    message_to_requirement = build_message_to_requirement_map(shapes_graph, ontology_graph)
    shape_to_requirement = build_shape_to_requirement_map(shapes_graph, ontology_graph)
    path_to_plain_shape = build_path_to_plain_shape_map(shapes_graph)

    rows = []
    for result in report_graph.subjects(RDF.type, SH.ValidationResult):
        focus_node = report_graph.value(result, SH.focusNode)
        message = report_graph.value(result, SH.resultMessage)
        severity = report_graph.value(result, SH.resultSeverity)
        result_path = report_graph.value(result, SH.resultPath)
        source_shape = report_graph.value(result, SH.sourceShape)

        requirement_id, requirement_description = lookup_requirement(
            source_shape, message, shape_to_requirement, message_to_requirement,
            result_path, path_to_plain_shape
        )

        rows.append({
            "Entity": str(focus_node) if focus_node is not None else "",
            "Requirement": requirement_id or "(not assigned)",
            "Warning": str(message) if message is not None else "",
            "Requirement description": requirement_description or "",
            "Severity": severity.split("#")[-1] if severity is not None else "",
            "Path": str(result_path) if result_path is not None else "",
        })

    # Sorted by entity, then requirement, so that the same devices stand together.
    rows.sort(key=lambda row: (row["Entity"], row["Requirement"]))

    fieldnames = ["Entity", "Requirement", "Warning", "Requirement description", "Severity", "Path"]
    # Semicolon and BOM (utf-8-sig), so that a European Excel reads the columns and special characters correctly.
    with open(output_path, "w", newline="", encoding="utf-8-sig") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)

    not_assigned = sum(1 for row in rows if row["Requirement"] == "(not assigned)")
    print(f"{len(rows)} message(s) found, written to: {output_path}")
    if not_assigned:
        print(f"Note: {not_assigned} of them could not be assigned to any requirement "
              "(neither shape nor message text nor path occur in the shape files).")


def main():
    parser = argparse.ArgumentParser(
        description="Summarizes a SHACL validation report clearly in a CSV file (semicolon, for Excel)."
    )
    parser.add_argument(
        "report", nargs="?", default=None,
        help="Path to the SHACL validation report (default: reports/shacl_report.csv of the only open crate)"
    )
    parser.add_argument(
        "--shapes", nargs="+",
        default=[str(path_definitions.CONTEXT_SHAPES), str(path_definitions.DATA_QUALITY_SHAPES)],
        help=f"Paths to the shape files (default: {path_definitions.CONTEXT_SHAPES} and {path_definitions.DATA_QUALITY_SHAPES})"
    )
    parser.add_argument(
        "--ontology", default=str(path_definitions.HLO_ONTOLOGY),
        help=f"Path to HigherLevelOntology.rdf, for the requirement descriptions (default: {path_definitions.HLO_ONTOLOGY})"
    )
    parser.add_argument(
        "--output", default=None,
        help="Path of the output file (default: reports/shacl_report_summarized.csv of the only open crate)"
    )
    args = parser.parse_args()

    if args.report is None or args.output is None:
        reports = path_definitions.reports_folder(path_definitions.identifier_of_crate(path_definitions.default_crate_path()))
        args.report = args.report or str(reports / path_definitions.SHACL_REPORT_NAME)
        args.output = args.output or str(reports / path_definitions.SHACL_REPORT_SUMMARIZED_NAME)
    summarize(args.report, args.shapes, args.ontology, args.output)


if __name__ == "__main__":
    main()
