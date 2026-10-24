// Reguły frontendu z CODING_STANDARDS, których Oxlint nie wyraża (brak no-restricted-syntax w Oxlint 1.88):
// 1. Każda właściwość schematów kontraktu (src/api/openapi.json) jest użyta w src poza generated/:
//    jej nazwa występuje jako identyfikator (dostęp, destrukturyzacja, klucz obiektu) albo tekst literału.
// 2. Przeglądarka nie porównuje nazwy procesu: żadnego `=== "settlement"` ani `case "preparation":`.
// 3. Sieć (fetch, EventSource, WebSocket, XMLHttpRequest, sendBeacon) i JSON.parse tylko w plikach src/api,
//    które parsują każdą odpowiedź serwera schematem z kontraktu.
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
])

// Pliki, które wolno rozgałęziać po nazwie procesu; każdy z uzasadnieniem.
const PROCESS_COMPARISON_FILES = new Map([
  ["src/pages/runs/run-setup-card.tsx", "wybór wejścia w karcie ustawień: Plik zbiorczy albo Rejestr zleceń"],
])

// Pliki, które wolno łączyć z serwerem; każdy z uzasadnieniem. Plik bez połączenia trzeba stąd usunąć.
const NETWORK_FILES = new Map([
  ["src/api/client.ts", "`call`: droga każdego zapytania, odpowiedź parsowana schematem z kontraktu"],
  ["src/api/centrum.ts", "strumień Uruchomień (każde zdarzenie parsowane zRunEvent) i pomiar widoku (204 bez treści)"],
])

const NETWORK_GLOBALS = new Set(["fetch", "EventSource", "WebSocket", "XMLHttpRequest"])

const GLOBAL_OBJECTS = new Set(["window", "globalThis", "self"])

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

function isInType(node) {
  for (let ancestor = node.parent; ancestor !== undefined; ancestor = ancestor.parent) {
    if (ts.isTypeNode(ancestor)) {
      return true
    }
  }

  return false
}

// `x.fetch` i `{ fetch: … }` to nazwy właściwości, nie globalny fetch; `window.fetch` i `{ fetch }` już tak.
function isNetworkGlobal(node) {
  if (!NETWORK_GLOBALS.has(node.text) || isInType(node)) {
    return false
  }

  const parent = node.parent

  if (ts.isPropertyAccessExpression(parent) && parent.name === node) {
    return ts.isIdentifier(parent.expression) && GLOBAL_OBJECTS.has(parent.expression.text)
  }

  return ts.isShorthandPropertyAssignment(parent) || parent.name !== node
}

function isNetworkMember(node) {
  return (
    ts.isPropertyAccessExpression(node) &&
    ts.isIdentifier(node.expression) &&
    ((node.expression.text === "JSON" && node.name.text === "parse") ||
      (node.expression.text === "navigator" && node.name.text === "sendBeacon"))
  )
}

function location(file, path, node) {
  const { line } = file.getLineAndCharacterOfPosition(node.getStart(file))

  return `${relative(root, path).replaceAll("\\", "/")}:${line + 1}: ${node.getText(file)}`
}

// Nazwy użyte w kodzie: identyfikatory (także dostęp do właściwości i destrukturyzacja) i teksty literałów.
function inspect(path, names, used, comparisons, network) {
  const file = ts.createSourceFile(path, readFileSync(path, "utf8"), ts.ScriptTarget.Latest, true)

  function visit(node) {
    if (ts.isIdentifier(node) || ts.isStringLiteralLike(node)) {
      used.add(node.text)
    }

    if (isProcessComparison(node, names)) {
      comparisons.push(location(file, path, node))
    }

    if ((ts.isIdentifier(node) && isNetworkGlobal(node)) || isNetworkMember(node)) {
      network.push(location(file, path, node))
    }

    ts.forEachChild(node, visit)
  }

  visit(file)
}

const contract = JSON.parse(readFileSync(join(source, "api", "openapi.json"), "utf8"))

const names = processNames(contract)

const used = new Set()

const comparisons = []

const network = []

const connectedFiles = new Set()

for (const path of sourceFiles(source)) {
  const key = relative(root, path).replaceAll("\\", "/")
  const calls = []
  inspect(path, names, used, PROCESS_COMPARISON_FILES.has(key) ? [] : comparisons, calls)

  if (calls.length > 0) {
    connectedFiles.add(key)
  }

  if (!NETWORK_FILES.has(key)) {
    network.push(...calls)
  }
}

const unused = contractFields(contract).filter((key) => !FIELDS_OUTSIDE_UI.has(key) && !used.has(fieldName(key)))

const staleExceptions = [...FIELDS_OUTSIDE_UI.keys()].filter((key) => used.has(fieldName(key)))

const staleNetworkFiles = [...NETWORK_FILES.keys()].filter((key) => !connectedFiles.has(key))

const problems = [
  ...unused.map((key) => `Pole kontraktu ${key} nie jest użyte w src: pokaż je w UI albo usuń z kontraktu.`),
  ...staleExceptions.map((key) => `Wyjątek ${key} jest zbędny: pole jest już użyte w src.`),
  ...comparisons.map((place) => `Porównanie nazwy procesu w przeglądarce: ${place}`),
  ...network.map(
    (place) =>
      `Sieć albo JSON.parse poza src/api: ${place}. Dodaj w src/api/centrum.ts funkcję, która woła serwer ` +
      "przez `call` z src/api/client.ts i parsuje odpowiedź schematem z kontraktu, i użyj jej tutaj.",
  ),
  ...staleNetworkFiles.map((key) => `Wyjątek ${key} w NETWORK_FILES jest zbędny: plik nie łączy się z serwerem.`),
]

for (const problem of problems) {
  console.error(problem)
}

if (problems.length > 0) {
  process.exit(1)
}

console.log("Reguły frontendu: OK")
