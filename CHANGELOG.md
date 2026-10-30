# Registro de mudanças

## 0.2.1

- **Corrigido:** no Windows, `Lume.exe --reset-colors` (recuperação de emergência,
  também usada ao desinstalar) não resetava as cores. Ele reaplicava a curva que
  já estava na tela, mesmo alterada. Agora grava curvas neutras. No macOS, usa o
  próprio sistema para reaplicar o perfil de cor (ColorSync).
- Primeira versão que pode ser instalada pela atualização dentro do app
  (a partir da 0.2.0).

## 0.2.0

- **Corrigido:** “Atualizar agora” não abria o instalador no Windows. O comando
  era montado com aspas escapadas de um jeito que o `cmd.exe` não entende, então
  o Lume fechava sem atualizar. A partir desta versão o instalador é iniciado
  corretamente, e um teste no Windows de verdade executa o comando a cada build.
- **Importante para quem tem a 0.1.0:** a atualização roda com o código da versão
  instalada, então a 0.1.0 não consegue se atualizar sozinha. Instale a 0.2.0
  manualmente (por cima, sem desinstalar; perfis e preferências são mantidos).
  Da 0.2.0 em diante, a atualização pelo app funciona.

## 0.1.0

- Primeira versão: brilho de hardware, temperatura de cor, escurecimento por
  software, filtros de cor experimentais, prévia, perfis, área de notificação,
  instalador Windows, atualizações com consentimento e fonte Inter.
