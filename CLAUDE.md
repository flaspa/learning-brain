# Learning Brain

## Goal

Build a personal learning-memory agent.

The first data source is a WhatsApp "Messages to yourself" export containing
links I have saved over several years, sometimes accompanied by short notes.

The system will eventually:

1. Parse saved URLs and my surrounding notes from WhatsApp.
2. Retrieve the actual content behind each URL using Bright Data.
3. Store and organize the resulting learning resources using Cognee.
4. Use AWS Strands Agents to reason over the library and invoke tools.
5. Later discover new learning material and relevant hackathons based on
   my interests and stored knowledge.
6. Optionally use Docker Sandboxes for safe execution and content processing.

## Current milestone

ONLY implement the WhatsApp parser.

Do not yet integrate Cognee, Bright Data, Strands, Docker, databases,
front-end frameworks, or unrelated infrastructure.

## Input

The real WhatsApp export is:

data/whatsapp/whatsApp_chat_flavspa.txt

This file contains private data and MUST NOT be committed to Git.

Example WhatsApp lines:

5/23/23, 11:18 AM - Flavia Sparacino: https://example.com/article

9/20/26, 8:09 PM - Flavia Sparacino: https://www.linkedin.com/...
9/20/26, 8:09 PM - Flavia Sparacino: Soo cool on gaussian processes

Messages may span multiple lines.

The export also contains system messages and "<Media omitted>" entries.

## Sender rule

For this dataset, retain only authored messages whose sender is exactly:

Flavia Sparacino

Ignore WhatsApp system messages.

## Parsing requirements

Extract URLs saved by Flavia Sparacino.

For each URL produce a normalized record containing at least:

- id
- timestamp
- url
- note_before
- note_after
- raw_message
- source

Set source to:

whatsapp_self_chat

Notes may occur in the same message as the URL or in nearby adjacent messages.

For the initial implementation:

- consider adjacent messages from Flavia within 5 minutes
- an adjacent note must not contain another URL
- ignore "<Media omitted>"
- do not treat WhatsApp system messages as notes
- preserve the original text
- support multiline messages
- if one WhatsApp message contains multiple URLs, create one resource record
  per URL while preserving the same message context

## Output

Write normalized JSON to:

output/whatsapp_links.json

The JSON should be UTF-8 and human readable.

Do not overwrite or modify the original WhatsApp export.

## Privacy

Never commit:

- data/
- output/
- .env
- credentials
- API keys
- private personal data

Use synthetic examples in tests if tests are added.

## Development principles

Keep the first implementation simple and deterministic.

Do not add abstractions unless they are needed.

Before changing the output schema, explain the reason.

After implementing a change:

1. run the parser
2. report how many messages were parsed
3. report how many URLs were found
4. report the first and last dates
5. show a few sanitized sample records
6. report parsing warnings or malformed records

Do not expose private message contents unnecessarily.