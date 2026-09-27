# ADR 0001: Lokalny deterministyczny silnik rozliczeń

## Status

Zaakceptowana

## Decyzja

Logika rozdzielania pliku zbiorczego do szablonów pracowników działa jako
lokalny, deterministyczny silnik Python. Udostępniamy dwie niezależne ścieżki
uruchomienia tego samego silnika: `Utwórz rozliczenia.cmd` oraz adapter VBA w
osobnym pliku `.xlsm`.

## Kontekst

Proces operuje na poufnych adresach i numerach zleceń. Potrzebuje filtrowania po
`WYKONAWCA`, kopiowania danych do wielu istniejących plików oraz zachowania
formuł szablonów. Tata używa desktopowego Excela na Windowsie. W przyszłości
możliwy jest wariant chmurowy, ale nie jest częścią pierwszej wersji.

## Rozważone warianty

### VBA jako jedyna implementacja

Pasuje do desktopowego Excela i ma dostęp do jego silnika. Wadą jest trudniejsze
testowanie bez Excela oraz zależność od polityki makr.

### Power Query

Dobrze filtruje i transformuje dane, ale fan-out do wielu gotowych workbooków z
indywidualnymi formułami wymaga dodatkowej warstwy sterującej.

### Office Scripts

Są naturalne dla Excela webowego i Power Automate, ale wprowadzają zależność od
OneDrive/SharePoint oraz odmiennych ograniczeń platformy.

### Python jako jedyny interfejs

Jest testowalny i lokalny, ale sam terminal byłby mniej wygodny dla taty.

## Konsekwencje

- Reguły biznesowe mają jedno źródło prawdy.
- Można testować transformację syntetycznymi workbookami.
- Tata może użyć prostego pliku `.cmd` albo przycisku w Excelu.
- Wdrożenie wymaga lokalnego Pythona; później można dodać opakowanie `.exe`.
- Makro nie ma dostępu do danych klientów poza przekazaniem ścieżki do lokalnego
  pliku, a właściwe przetwarzanie wykonuje ten sam kod co ścieżka `.cmd`.
