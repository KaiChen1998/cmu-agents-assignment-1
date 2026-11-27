# DeepSeek observation experiment

Both runs used `deepseek-flash`, the same starting position, and the same deterministic Black bot.
Each run used a 200-step limit and a 30-minute sandbox limit. The board-only condition included the FEN.
The other condition also displayed the current legal UCI moves.

| Observation | `play_move` calls | Rejected as illegal | Illegal rate | Other tool errors | Reached `game_over` | Outcome |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| Board and FEN | 57 | 2 | 3.51% | 0 | No | 30-minute sandbox limit |
| Board, FEN, and legal moves | 46 | 0 | 0.00% | 0 | No | 30-minute sandbox limit |

The illegal rate is the number of moves rejected as illegal in the current position divided by all `play_move` calls.
Counts use the linked tool observations, including the final turn.

With the legal-move list, the observed illegal rate fell from 3.51% to 0.00%, a decrease of 3.51 percentage points. The list let the model choose directly from the server's legal moves.
There was one game per condition. The games reached different positions, so the observed finish status and call counts alone give limited evidence about overall playing strength or speed.

## Why these games took longer

The earlier Part 3.1 game used the same model and the legal-move list. It ended with a White win in 39 actions, and its moves diverged from the A/B legal-list game on White's fifth turn.
In the A/B legal-list game, median reasoning increased from 1,283 to 4,169.5 tokens per completed response. The last completed request used 377,575 input tokens, compared with 120,052 in the Part 3.1 game.
The configured OpenAI-style output cap was 4,096, while DeepSeek reported up to 42,106 completion tokens in the A/B legal-list game. DeepSeek's native API documents the output cap as `max_tokens`. [DeepSeek Chat Completions documentation](https://api-docs.deepseek.com/api/create-chat-completion/)
Both A/B runs were stopped at the shared 30-minute sandbox limit with a model request still in flight. The table counts completed model responses and observed tool outcomes.

## Run evidence

- Board and FEN — [trajectory](part3-no-legal-moves-deepseek.json), [result](part3-no-legal-moves-deepseek-result.json)
- Board, FEN, and legal moves — [trajectory](part3-legal-moves-deepseek.json), [result](part3-legal-moves-deepseek-result.json)
