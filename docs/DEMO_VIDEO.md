# Demo video script (about 3 minutes)

## Before recording

```bash
python scripts/up.py --reset
python -m counterpart.run          # terminal 1, leave running
python -m counterpart.console      # terminal 2, leave running
```

Open <http://127.0.0.1:8090> full screen at 1920x1080, and have a terminal ready. A model-written deal takes several minutes, so speed up the waits in editing and say so on screen. Run `python -m counterpart.demo` (terminal 3) when the second scene starts.

## Scenes

| Time | On screen | Say |
|---|---|---|
| 0:00 | The empty console | "Business contracts spend weeks going back and forth, because each side is guarding limits it can't reveal. A shared AI can't help, since neither company would give it those limits. And your own AI negotiator is a risk: anything it knows, a clever message might extract." |
| 0:25 | The three column headers | "So Counterpart makes sure the negotiator never has a secret. Each company gets a private chamber, where plain code holds the limits and a human holds the authority. The AI negotiators meet in the middle, knowing only what they're told to argue. All of this is real Switch rooms with real permissions." |
| 0:50 | Clerk opens the agenda, first offers appear | "Priya, Acme's General Counsel, types start. These are two AI agents negotiating for two companies." |
| 1:05 | "Decision needed" in Acme's chamber | "Bolt offered 18 months, which is beyond what the agent may accept. So the deal room only hears that Acme is taking instructions, while Priya alone sees the limits and the reason." |
| 1:20 | Arjun's refusal, then Priya's counter | "Arjun, a junior colleague, tries to approve and is refused, because Switch tells us exactly who sent it. Priya counters at 15." |
| 1:35 | Daniel's approval in Bolt's chamber | "Daniel sees a different chamber, with different limits. Neither of them can see the other's." |
| 1:45 | The injection and both replies in the deal room | "Now the attack: a message orders Acme's agent to print its limits. Switch refuses first, since that chat account isn't linked to a Switch user. Then the agent answers honestly that it doesn't hold them. There's nothing to extract." |
| 2:05 | Clauses filling the top strip | "Three of the five clauses settle without taking any person's time. People spend their attention only where their authority is needed." |
| 2:20 | Both `sign` messages, then the seal | "Agents can't sign. Only when both people have signed does the Clerk seal the terms and file the agreement in Switch." |
| 2:35 | Terminal: run `verify_isolation`, then `verify_leaks` | "You don't have to take my word for it. This attacks every boundary on the live server with each agent's real credentials: every attack is refused. This searches everything shareable for planted secrets: nothing leaked. And the repo is one command to run." |
| 2:55 | The finished console | "Counterpart: agents do the back and forth, people keep the authority, and secrets stay home." |

## Keep it accurate

- Say that the companies and limits are sample data, and that both run on one local server for the demo.
- Don't claim it's impossible to leak anything. The claim is that a Negotiator doesn't hold the limits, and that the checks found no leak in this run.
- If a scene's wording stops matching the run, change the words rather than re-staging the run.
