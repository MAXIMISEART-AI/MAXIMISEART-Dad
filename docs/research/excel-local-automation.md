# Research: lokalna automatyzacja Excel

Data researchu: 2026-09-27

## Wniosek

Najlepszy wariant dla tego procesu to lokalny, deterministyczny silnik Python z
dwoma adapterami uruchomieniowymi:

- plik `.cmd`, który tata może uruchomić dwuklikiem;
- moduł VBA importowany do osobnego pliku `.xlsm` z przyciskiem.

Oba adaptery uruchamiają dokładnie ten sam silnik. Dane nie są wysyłane do AI,
API ani usługi analitycznej.

## VBA

Microsoft dokumentuje `Range.AutoFilter` do filtrowania listy oraz
`Workbook.SaveAs` do zapisywania workbooka pod inną nazwą. VBA ma bezpośredni
dostęp do desktopowego Excela, więc dobrze pasuje do zachowania formuł i
formatowania istniejącego szablonu.

Wadą są ustawienia bezpieczeństwa makr. Microsoft opisuje, że makra mogą być
blokowane, a zaufana lokalizacja lub podpisany kod zmieniają ten model ryzyka.
Dlatego makro nie jest dodawane do plików zbiorczych; adapter ma działać w
osobnym, zaufanym pliku `.xlsm`.

Źródła:

- [Range.AutoFilter](https://learn.microsoft.com/en-us/office/vba/api/excel.range.autofilter)
- [Workbook.SaveAs](https://learn.microsoft.com/en-us/office/vba/api/excel.workbook.saveas)
- [Excel macro security](https://support.microsoft.com/en-us/excel/change-macro-security-settings-in-excel)
- [Trusted locations](https://support.microsoft.com/en-us/office/security-privacy/add-remove-or-change-a-trusted-location-in-microsoft-office)

## Power Query

Power Query dobrze filtruje wiersze i ładuje dane do Excela. Dokumentacja
Microsoft opisuje także łączenie plików z folderu. Nie jest to jednak naturalny
mechanizm wykonania fan-outu: jeden zbiorczy arkusz -> osobny zapis do wielu
istniejących workbooków pracowników z zachowaniem ich indywidualnych formuł.

Źródła:

- [Filtering values in Power Query](https://learn.microsoft.com/en-us/power-query/filter-values)
- [Power Query Folder connector](https://learn.microsoft.com/en-us/power-query/connectors/folder)
- [Combine files overview](https://learn.microsoft.com/en-us/power-query/combine-files-overview)

## Office Scripts

Office Scripts są wygodne dla Excela webowego i Power Automate, ale skrypty są
przechowywane w OneDrive lub SharePoint i wymagają dostępu do tych lokalizacji.
Microsoft wskazuje także ograniczenia platformy oraz różnice między Excel web a
desktopem. To nie jest właściwy pierwszy wariant dla lokalnego procesu z
poufnymi plikami.

Źródła:

- [Office Scripts platform limits](https://learn.microsoft.com/en-us/office/dev/scripts/testing/platform-limits)
- [Office Scripts storage](https://learn.microsoft.com/en-us/office/dev/scripts/overview/script-storage)
- [Office Scripts and Power Automate example](https://learn.microsoft.com/en-us/office/dev/scripts/resources/samples/convert-csv)

## Python i `openpyxl`

Python daje testowalny, lokalny silnik bez automatyzowania interfejsu Excela.
W tym procesie kopiowane są wyłącznie wartości `A:AT`; formuły `AU:AY` zostają
w szablonie. Po zapisie workbook jest oznaczany do ponownego przeliczenia po
otwarciu w Excelu.

To ogranicza ryzyko zmian w formule źródłowej i pozwala testować logikę na
syntetycznych plikach bez danych klientów. Wariant VBA pozostaje dostępny jako
adapter dla taty, ale reguły biznesowe są utrzymywane tylko w jednym silniku.

## RODO i AI

RODO nie wprowadza prostego zakazu używania AI na danych osobowych. Przetwarzanie
przez zewnętrzne AI wymagałoby jednak osobnej analizy podstawy prawnej, celu,
minimalizacji, roli dostawcy, retencji, bezpieczeństwa i ewentualnego transferu
poza EOG. EROD wskazuje, że zarówno rozwój, jak i wdrożenie modeli AI może
obejmować osobne operacje przetwarzania danych osobowych.

W tym projekcie AI nie jest potrzebne, dlatego decyzja brzmi: **nie przekazujemy
AI żadnych danych klientów**. Lokalny kod nadal jest przetwarzaniem danych, ale
nie dodaje zewnętrznego odbiorcy.

Źródła:

- [RODO: definicje i procesor, EUR-Lex](https://eur-lex.europa.eu/eli/reg/2016/679/oj)
- [EDPB Opinion 28/2024 on AI models](https://www.edpb.europa.eu/system/files/2024-12/edpb_opinion_202428_ai-models_en.pdf)
- [UODO: zanim wdrożysz AI](https://uodo.gov.pl/pl/138/4533)
