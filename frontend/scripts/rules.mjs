// Reguły frontendu z CODING_STANDARDS, których Oxlint nie wyraża (brak no-restricted-syntax w Oxlint 1.88):
// 1. Każda właściwość schematów kontraktu (src/api/openapi.json) jest użyta w src poza generated/:
//    jej nazwa występuje jako identyfikator (dostęp, destrukturyzacja, klucz obiektu) albo tekst literału.
// 2. Przeglądarka nie porównuje nazwy procesu: żadnego `=== "settlement"` ani `case "preparation":`.
import { readdirSync, readFileSync } from "node:fs"
import { join, relative, resolve } from "node:path"
import ts from "typescript"

const root = resolve(import.meta.dirname, "..")

const source = join(root, "src")

const generated = join(source, "api", "generated")

// Schematy kontraktu spoza UI; każdy z uzasadnieniem.
const SCHEMAS_OUTSIDE_UI = new Map([
  ["HTTPValidationError", "domyślny błąd walidacji FastAPI; przeglądarka pokazuje własny Komunikat błędu"],
  ["ValidationError", "domyślny błąd walidacji FastAPI, część HTTPValidationError"],
])

// Pola kontraktu, których UI nie pokazuje; każde z uzasadnieniem. Pole użyte w src trzeba stąd usunąć.
const FIELDS_OUTSIDE_UI = new Map([
  ["Health.service", "czyta je launcher Centrum (launcher.py), nie przeglądarka"],
  ["RunEvent.sequence", "numer zdarzenia strumienia SSE, nie treść dla taty"],
  ["RunOutcome.stop_kind", "rodzaj Zatrzymania z widoku wyniku (spec #153); przeglądarka pokazuje, co z niego wynika: RunOutcome.diagnosis"],
])

// Pliki, które wolno rozgałęziać po nazwie procesu; każdy z uzasadnieniem.
const PROCESS_COMPARISON_FILES = new Map([
  ["src/pages/runs/run-setup-card.tsx", "wybór wejścia w karcie ustawień: Plik zbiorczy albo Rejestr zleceń"],
])

function sourceFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name)

    if (entry.isDirectory()) {
      return path === generated ? [] : sourceFiles(path)
    }

    return /\.tsx?$/.test(entry.name) ? [path] : []
  })
}

function contractFields(contract) {
  return Object.entries(contract.components.schemas)
    .filter(([schema]) => !SCHEMAS_OUTSIDE_UI.has(schema))
    .flatMap(([schema, definition]) => Object.keys(definition.properties ?? {}).map((field) => `${schema}.${field}`))
}

function fieldName(key) {
  return key.split(".")[1]
}

function processNames(contract) {
  return new Set(contract.components.schemas.RunRequest.properties.process.enum)
}

function isProcessName(node, names) {
  return ts.isStringLiteralLike(node) && names.has(node.text)
}

const COMPARISONS = new Set([
  ts.SyntaxKind.EqualsEqualsEqualsToken,
  ts.SyntaxKind.ExclamationEqualsEqualsToken,
  ts.SyntaxKind.EqualsEqualsToken,
  ts.SyntaxKind.ExclamationEqualsToken,
])

function isProcessComparison(node, names) {
  if (ts.isBinaryExpression(node) && COMPARISONS.has(node.operatorToken.kind)) {
    return isProcessName(node.left, names) || isProcessName(node.right, names)
  }

  return ts.isCaseClause(node) && isProcessName(node.expression, names)
}

// Nazwy użyte w kodzie: identyfikatory (także dostęp do właściwości i destrukturyzacja) i teksty literałów.
function inspect(path, names, used, comparisons) {
  const file = ts.createSourceFile(path, readFileSync(path, "utf8"), ts.ScriptTarget.Latest, true)

  function visit(node) {
    if (ts.isIdentifier(node) || ts.isStringLiteralLike(node)) {
      used.add(node.text)
    }

    if (isProcessComparison(node, names)) {
      const { line } = file.getLineAndCharacterOfPosition(node.getStart(file))
      comparisons.push(`${relative(root, path)}:${line + 1}: ${node.getText(file)}`)
    }

    ts.forEachChild(node, visit)
  }

  visit(file)
}

const contract = JSON.parse(readFileSync(join(source, "api", "openapi.json"), "utf8"))

const names = processNames(contract)

const used = new Set()

const comparisons = []

for (const path of sourceFiles(source)) {
  const allowed = PROCESS_COMPARISON_FILES.has(relative(root, path).replaceAll("\\", "/"))
  inspect(path, names, used, allowed ? [] : comparisons)
}

const unused = contractFields(contract).filter((key) => !FIELDS_OUTSIDE_UI.has(key) && !used.has(fieldName(key)))

const staleExceptions = [...FIELDS_OUTSIDE_UI.keys()].filter((key) => used.has(fieldName(key)))

const problems = [
  ...unused.map((key) => `Pole kontraktu ${key} nie jest użyte w src: pokaż je w UI albo usuń z kontraktu.`),
  ...staleExceptions.map((key) => `Wyjątek ${key} jest zbędny: pole jest już użyte w src.`),
  ...comparisons.map((place) => `Porównanie nazwy procesu w przeglądarce: ${place}`),
]

for (const problem of problems) {
  console.error(problem)
}

if (problems.length > 0) {
  process.exit(1)
}

console.log("Reguły frontendu: OK")
