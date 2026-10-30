# Lume — brilho e cor da tela

Aplicativo desktop para ajustar **brilho**, **temperatura de cor** e **filtros de cor opcionais**, com foco em conforto visual, acessibilidade e controle total pela pessoa usuária.

- Brilho, temperatura e filtros são **independentes**. Nenhum ajuste é aplicado automaticamente nem associado a diagnósticos.
- Os filtros são **experimentais** e **não** são tratamento ou correção médica; o efeito varia entre pessoas e monitores.
- O programa não coleta dados pessoais nem de saúde. Ele só guarda perfis e preferências neste computador.

## Plataforma principal: Windows (com instalador)

| Recurso | Como funciona no Windows | Observações |
|---|---|---|
| Brilho da tela integrada (notebook) | WMI (`WmiMonitorBrightnessMethods`) | Funciona na maioria dos notebooks. |
| Brilho de monitor externo | DDC/CI (`dxva2.dll`) | Só se o monitor tiver DDC/CI **ligado** no menu dele. Alguns adaptadores, docks e TVs bloqueiam. |
| Temperatura de cor | Curva de gama (`SetDeviceGammaRamp`) | O Windows recusa curvas muito extremas: o app avisa e não contorna essa proteção. Com **HDR** ativo ou **Luz Noturna** do Windows ligada, o sistema pode ignorar ou sobrepor o ajuste. |
| Escurecimento por software | Mesma curva de gama | Reduz as cores, **não** a luz de fundo. Mínimo de 20 % para a tela nunca ficar preta. |
| Filtros de cor | Magnification API (`MagSetFullscreenColorEffect`, Windows 8+) | Só ficam ativos enquanto o app está aberto. Exigem Python/executável 64 bits em Windows 64 bits. |
| Área de notificação | Ícone na bandeja | Ao **minimizar** ou **fechar**, o app vai para a área de notificação (as duas opções podem ser desligadas no menu *Ajustes*). |
| Iniciar com o Windows | Valor em `HKCU\…\Run` | Opcional, no instalador ou no menu *Ajustes*. Abre direto na área de notificação. |

Nenhum recurso do app pede privilégio de administrador. O instalador, por padrão, instala só para o usuário atual (sem administrador); ele também oferece instalar para todos os usuários, e nesse caso o Windows pede permissão de administrador.

### Outros sistemas (suporte secundário)

- **Linux X11:** temperatura e escurecimento por XRandR; luz de fundo por `systemd-logind` (sem root na sessão local ativa); monitores externos por `ddcutil` (exige o módulo `i2c-dev` e acesso a `/dev/i2c-*`, normalmente pelo grupo `i2c`).
- **Linux Wayland:** o compositor controla as cores, então temperatura e escurecimento ficam indisponíveis (o app sugere a Luz Noturna do GNOME, a Cor Noturna do KDE ou gammastep/wlsunset). O brilho continua funcionando por logind/ddcutil.
- **macOS:** temperatura e escurecimento via CoreGraphics. O brilho de hardware fica indisponível porque não existe API pública estável (o app não usa APIs privadas). Para filtros, use *Ajustes do Sistema › Acessibilidade › Tela › Filtros de cor*.
- **Filtros no Linux/macOS:** funcionam **só na prévia** do app, porque não existe API pública de matriz de cor para a tela inteira.

O menu **Ajuda › Compatibilidade desta tela** mostra o que funciona na sua máquina e por quê.

## Instalar no Windows

Requisitos: Windows 10 ou 11, 64 bits.

1. Abra a **[versão mais recente](https://github.com/geandreac/screen-brightness/releases/latest)**.
2. Em **Assets**, baixe `Lume-Setup-<versão>.exe` e execute.
3. Depois de instalado, o Lume pode se atualizar sozinho (veja [Atualizações automáticas](#atualizações-automáticas)).

> **Aviso do Windows (SmartScreen):** o instalador ainda não tem assinatura digital, então o Windows pode mostrar “O Windows protegeu o computador”. Para instalar, clique em **Mais informações › Executar assim mesmo**. Para conferir que o arquivo é o original, compare o SHA‑256 (`Get-FileHash .\Lume-Setup-<versão>.exe`) com o valor exibido ao lado do arquivo na página da release.

Os instaladores de cada commit também ficam disponíveis por um tempo na aba **Actions** (artefato **Lume-Setup**, exige login no GitHub). Para uso normal, prefira a página de versões.

### Gerar o instalador na sua máquina

Pré-requisitos: Python 3.10+ (64 bits) e [Inno Setup 6](https://jrsoftware.org/isdl.php).

```powershell
.\packaging\build_windows.ps1
```

O resultado fica em `dist\installer\Lume-Setup-<versão>.exe`. Para gerar só o executável, sem instalador:

```powershell
pyinstaller packaging\lume.spec --noconfirm
```

## Atualizações automáticas

- **Só com autorização.** Na primeira execução, um aviso pergunta se o Lume pode verificar novas versões uma vez por dia. A opção pode ser mudada a qualquer momento em **Ajustes › Verificar atualizações automaticamente**, e há também **Ajuda › Verificar atualizações agora**.
- A verificação consulta apenas a API pública de releases do GitHub. Nenhum dado pessoal é enviado.
- Quando há versão nova, aparece um aviso com **Atualizar agora**, **Ver novidades**, **Depois** e **Pular esta versão**. Nada é baixado sem clique.
- **Atualizar agora** (só no app instalado no Windows) pede confirmação e baixa o `Lume-Setup-<versão>.exe` da release. Antes de executar, o app confere o tamanho e o **SHA‑256** informado pelo GitHub. Depois fecha (restaurando as cores), instala em modo silencioso e reabre o app. Perfis e preferências são mantidos.
- Rodando a partir do código ou fora do Windows, o aviso apenas abre a página da release.

### Publicar uma nova versão

1. Atualize a versão em `src/lume/__init__.py` (`__version__`) e em `pyproject.toml`.
2. Faça commit e crie a tag correspondente:

```bash
git tag v0.2.0
```

```bash
git push origin main v0.2.0
```

3. O workflow gera o instalador e cria a release com o `Lume-Setup-0.2.0.exe` anexado. A partir daí, os apps instalados com a verificação ligada passam a oferecer a atualização.

## Rodar a partir do código

```bash
python -m venv .venv
```

```bash
.venv/bin/pip install -r requirements-dev.txt
```

No Windows, use `.venv\Scripts\pip` e `.venv\Scripts\python`.

```bash
PYTHONPATH=src .venv/bin/python -m lume
```

Opções:

- `--demo` — modo demonstração, sem alterar a tela de verdade.
- `--tray` — inicia escondido, só com o ícone na área de notificação.
- `--reset-colors` — restaura curvas de cor lineares e sai. Use se o app foi encerrado à força com cores alteradas.

## Testes

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python -m pytest -q
```

## Como usar

- **Aplicar imediatamente** (rodapé): ligado, brilho e temperatura mudam enquanto você ajusta; desligado, você confere na prévia e clica em **Aplicar** (Ctrl+Enter).
- **Filtros** nunca vão para a tela sem um clique em *Aplicar filtro à tela*. Ao ativar um filtro, ele é **desfeito sozinho em 15 s** se você não confirmar (ou se pressionar Esc). Isso evita ficar preso com uma tela difícil de ler.
- **Comparar com original**: segure o botão (ou use Ctrl+Shift+O) para ver as cores sem ajustes, sem perder suas escolhas.
- **Restaurar originais** (Ctrl+R): volta brilho e cores ao estado de quando o app abriu, com opção de desfazer.
- **Perfis**: salve combinações com o nome que quiser (por exemplo “Dia” ou “Noite”). Nenhum perfil é aplicado automaticamente.
- **Texto**: Ctrl+= / Ctrl+- / Ctrl+0 ampliam ou reduzem a interface (80–200 %), além da escala do sistema.
- **Transições suaves** podem ser desligadas. Ficam desligadas por padrão se o sistema pedir redução de movimento.
- Ao **sair** (menu da bandeja › *Sair e restaurar cores*), temperatura, escurecimento e filtros voltam ao original. O brilho de hardware permanece como está, igual ao controle de brilho do sistema.

## Fonte

A interface usa a **[Inter](https://rsms.me/inter/)** 4.1 (pesos 400 e 600), incluída no app em `src/lume/assets/fonts/` sob a **SIL Open Font License 1.1** (texto completo em `OFL.txt`, junto dos arquivos). Assim a aparência é a mesma no Windows, no macOS e no Linux. Se a fonte não carregar, o app volta para a fonte do sistema.

A SF Pro não é usada porque a licença da Apple só permite usá‑la em software para plataformas Apple, e proíbe redistribuí‑la.

## Arquitetura

```
src/lume/
  core/       lógica sem interface: modelos, matemática de cor, motor de aplicação
              (thread própria, transições, "o pedido mais recente vence"), perfis
  platform/   um backend por sistema (windows, linux, macos) + mock para testes/demo
  ui/         PySide6: janela, tema escuro, prévia, bandeja, instância única
packaging/    PyInstaller (.spec), Inno Setup (.iss), script de build no Windows
```

Cada backend declara em `probe()` o que de fato suporta. A interface só habilita o que está disponível e explica o motivo do que não está.

## Licença

O código do Lume é distribuído sob a **[licença MIT](LICENSE)**. A fonte Inter, incluída no app, tem licença própria (SIL Open Font License 1.1; veja `src/lume/assets/fonts/OFL.txt`).

## Ainda não implementado

- Agendamento automático por horário (os perfis são aplicados manualmente).
- Atalhos de teclado globais (fora da janela).
- Assinatura digital do instalador (a integridade do download é conferida por SHA‑256, mas o Windows SmartScreen ainda mostra “editor desconhecido”).
- Controle de brilho de hardware no macOS e filtros de tela inteira no Linux/macOS (não há API pública).
