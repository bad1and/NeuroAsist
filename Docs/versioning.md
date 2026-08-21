# Versioning

## Источник истины

Корневой файл [`VERSION`](../VERSION) содержит SemVer продукта без префикса
`v`, например `1.0.0`. Это единственное значение, которое выбирает человек при
подготовке версии.

Некоторые инструменты требуют собственное поле version, поэтому значение
зеркалируется в:

- `package.json` и собственном root record `package-lock.json`;
- `apps/web/package.json` и двух собственных records его lockfile;
- `apps/desktop/package.json` и собственном root record lockfile;
- `apps/desktop/src-tauri/Cargo.toml` и package block `neuroasist-desktop` в `Cargo.lock`;
- `apps/desktop/src-tauri/tauri.conf.json`;
- `apps/avatar-unity/ProjectSettings/ProjectSettings.asset` (`bundleVersion`);
- FastAPI/OpenAPI и `/status`, которые читают `VERSION` при запуске.

README badge также должен показывать текущее значение. Проверка:

```powershell
.\.venv\Scripts\python.exe scripts/check_docs.py
```

## Что не является версией приложения

Не заменяйте массовым search/replace:

- `protocol_version` Character/Avatar/Voice;
- SQLite schema migration numbers;
- memory `pipeline_version`, extractor/generator versions;
- model/dependency versions;
- `Docs/archive/**` и `version-manifest-v0.4.1.json`;
- имена legacy tables/fixtures и migration regression tests.

Эти значения имеют собственные compatibility contracts и меняются только
вместе с соответствующей миграцией.

## Подготовка новой версии

1. Изменить `VERSION`.
2. Обновить версии трёх npm packages штатной командой:

   ```powershell
   npm version <version> --no-git-tag-version
   npm --prefix apps/web version <version> --no-git-tag-version
   npm --prefix apps/desktop version <version> --no-git-tag-version
   ```

3. Обновить `Cargo.toml`, `tauri.conf.json` и Unity `bundleVersion`.
4. Запустить `cargo check --manifest-path apps/desktop/src-tauri/Cargo.toml`, чтобы Cargo обновил только собственный package block lockfile.
5. Обновить current-version формулировки и release notes, не переписывая архив.
6. Запустить docs/version check и полную verification matrix.
7. После одобрения release checklist создать annotated tag `v<version>` на проверенном commit.

Lockfiles изменяются штатными npm/Cargo инструментами. Нельзя заменять каждое
совпадение старой версии внутри lockfile: большая часть совпадений принадлежит
зависимостям.

## Release channels

- `X.Y.Z` — stable candidate metadata; публикация разрешена только после checklist.
- `X.Y.Z-rc.N` — release candidate, если решено распространять тестовый installer.
- `X.Y.Z-dev.N` — локальная/ночная линия, которая не должна публиковаться как stable.

Git branch name не задаёт version. Branch может сохранять историческое имя, но
tag и artifact metadata обязаны совпадать с `VERSION`.

## Toolchain versions

Продуктовая версия не равна версии toolchain. Проверенные development tools:
`.python-version` (`3.12.1`), `.nvmrc` (`24.18.0`) и stable Rust `1.95.0` на
момент проверки. `rust-toolchain.toml` выбирает установленный `stable`, а
`Cargo.toml` сохраняет `rust-version = 1.77.2` как минимальный compatibility
contract. Unity editor version находится в
`apps/avatar-unity/ProjectSettings/ProjectVersion.txt`.
