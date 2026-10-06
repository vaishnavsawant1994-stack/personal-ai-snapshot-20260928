"""Persist the UI reference examples in the app's existing owner stores.

Run with ``python -m tools.seed_reference_dataset --apply``. This is always an
explicit action: it does not seed at startup. Existing stores remain canonical;
all records are labeled as illustrative examples and can be removed normally.
"""
from __future__ import annotations

import argparse
import json
import os
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from core.config import settings
except ModuleNotFoundError as exc:
    if exc.name != 'dotenv':
        raise
    class _Settings:
        data_dir = Path(os.getenv('PERSONAL_AI_DATA_DIR', str(Path.home() / '.personal_ai'))).expanduser().resolve()
    settings = _Settings()
from devices.continuity import ContinuityService
_everyday_spec = importlib.util.spec_from_file_location('_vishnu_seed_everyday', Path(__file__).resolve().parents[1] / 'future_intelligence' / 'everyday.py')
if _everyday_spec is None or _everyday_spec.loader is None:
    raise RuntimeError('The canonical Everyday store implementation could not be loaded')
_everyday_module = importlib.util.module_from_spec(_everyday_spec)
sys.modules[_everyday_spec.name] = _everyday_module
_everyday_spec.loader.exec_module(_everyday_module)
EverydayIntelligence = _everyday_module.EverydayIntelligence
from knowledge.store import KnowledgeStore
from memory.second_brain import MemoryCandidate, SecondBrain
from memory.store import MemoryStore
from projects.store import ProjectStore

MARKER = 'reference-example-dataset-v1'


def seed(data_dir: Path, timezone_name: str = 'UTC') -> dict:
    """Create missing illustrative rows only; safe to run more than once."""
    zone = ZoneInfo(timezone_name)
    data_dir = Path(data_dir).expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    memory = MemoryStore(data_dir / 'assistant.sqlite3')
    brain = SecondBrain(memory)
    continuity = ContinuityService(data_dir / 'continuity.sqlite3', second_brain=brain)
    everyday = EverydayIntelligence(data_dir / 'future-intelligence' / 'everyday.sqlite3', memory=memory, second_brain=brain,
                                    continuity=continuity, timezone_name=timezone_name)
    projects = ProjectStore(data_dir / 'projects.sqlite3')
    knowledge = KnowledgeStore(data_dir / 'knowledge.sqlite3', data_dir / 'knowledge' / 'objects')

    today = datetime.now(zone).date()
    stamp = datetime.now(timezone.utc)
    def local_at(day_offset: int, hour: int, minute: int = 0) -> str:
        local = datetime.combine(today + timedelta(days=day_offset), datetime.min.time(), tzinfo=zone)
        return (local + timedelta(hours=hour, minutes=minute)).isoformat()

    def sample_pdf(text: str) -> bytes:
        clean = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)').encode('ascii', 'replace')
        stream = b'BT /F1 12 Tf 72 720 Td (' + clean + b') Tj ET'
        objects = [
            b'<< /Type /Catalog /Pages 2 0 R >>',
            b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
            b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
            b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream',
            b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        ]
        out = bytearray(b'%PDF-1.4\n')
        offsets = [0]
        for number, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out.extend(f'{number} 0 obj\n'.encode() + body + b'\nendobj\n')
        xref = len(out)
        out.extend(f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode())
        for offset in offsets[1:]:
            out.extend(f'{offset:010d} 00000 n \n'.encode())
        out.extend(f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
        return bytes(out)

    created = {'everyday': [], 'projects': [], 'conversations': [], 'memories': [], 'knowledge': [], 'collections': []}
    marker_project_ids = set()
    project_map = {item['name']: item for item in projects.list(status='all')}
    for name, goal, desc in [
        ('Personal AI workspace redesign', 'Example workspace for the Today, Memory, Knowledge, and Activity reference flows.', 'Illustrative reference data. These rows demonstrate how Personal AI features connect; they are not verified work history.'),
        ('Vishnu Projects workspace', 'Example project linked to due tasks in Today.', 'Illustrative reference data. This is a saved example project, not an active user commitment.'),
    ]:
        project = project_map.get(name)
        if project is not None and not project.get('is_walkthrough'):
            # Never attach sample tasks to an existing real project with a matching name.
            project = None
            sample_name = f'{name} · Example'
        else:
            sample_name = name
        if project is None:
            project = projects.create(name=sample_name, goal=goal, description=desc, project_type='software')
            created['projects'].append(project['id'])
            with projects.con() as con:
                con.execute('UPDATE projects SET is_walkthrough=1 WHERE id=?', (project['id'],))
        marker_project_ids.add(project['id'])
        project_map[name] = projects.get(project['id'])

    project_tasks = [
        ('Personal AI workspace redesign', 'Finalize settings design', 'Confirm the memory and settings controls layout.', 1),
        ('Vishnu Projects workspace', 'Prepare project doc', 'Collect the key workspace decisions in a short project document.', 2),
        ('Vishnu Projects workspace', 'Review Vishnu Projects workspace', 'Test the latest changes and document feedback.', 0),
    ]
    for project_name, title, description, due_offset in project_tasks:
        project = project_map[project_name]
        if any(task['title'] == title for task in project['tasks']):
            continue
        project = projects.add_task(project['id'], title=title, description=description,
                                    owner='owner', priority='medium', due_date=(today + timedelta(days=due_offset)).isoformat())
        created['projects'].append(project['tasks'][-1]['id'])

    # Plans map to the app's existing canonical Everyday goal type. Meetings
    # use the existing commitment type. Neither creates a parallel task table.
    for kind, title, due, description in [
        ('task', 'Review Personal AI mobile UI', local_at(0, 9, 30), 'Go through the reference screens and share feedback.'),
        ('commitment', 'Design review', local_at(0, 11), 'Discuss mobile UI and agree on next steps.'),
        ('goal', 'Plan tomorrow', local_at(0, 16, 30), 'Review today and set priorities for tomorrow.'),
    ]:
        existing_item = None
        with everyday._con() as con:
            row = con.execute('SELECT id FROM everyday_items WHERE source=? AND title=? LIMIT 1', (MARKER, title)).fetchone()
            existing_item = row['id'] if row else None
            if existing_item:
                con.execute('UPDATE everyday_items SET context=? WHERE id=?', (f'personal-ai:today:{kind} · {MARKER}: {description}', existing_item))
        if not existing_item:
            item_id = everyday.add(kind, title, due_at=due, context=f'personal-ai:today:{kind} · {MARKER}: {description}', source=MARKER,
                                   timezone_name=timezone_name, now=stamp)
            created['everyday'].append(item_id)

    conversations = [
        ('Today page spacing review', 'The bottom actions should match across pages and leave clear space around section headings.'),
        ('Personal AI mobile redesign', 'The responsive reference keeps the navigation compact and the action bar within the safe area.'),
        ('Project workspace planning', 'Keep project goals, milestones, and follow-up tasks together in the workspace.'),
        ('Memory and saved context', 'Personal memory stores user context; project decisions remain with the project.'),
    ]
    existing_threads = continuity.list_threads(limit=200, include_closed=True)
    for title, text in conversations:
        existing = next((t for t in existing_threads if t['title'] == title and t.get('context', {}).get('dataset') == MARKER), None)
        if existing:
            continue
        thread_id = continuity.create_thread(title, context={'dataset': MARKER, 'illustrative_example': True})
        continuity.append(thread_id, device_id='reference-dataset', kind='user_message',
                          payload={'text': text, 'illustrative_example': True}, event_id=f'{MARKER}:{title}:user')
        continuity.append(thread_id, device_id='reference-dataset', kind='assistant_message',
                          payload={'text': 'Saved as an illustrative reference example. Update or remove it whenever you like.', 'illustrative_example': True},
                          event_id=f'{MARKER}:{title}:assistant')
        created['conversations'].append(thread_id)
        existing_threads.append({'id': thread_id, 'title': title, 'context': {'dataset': MARKER}})

    memory_examples = [
        ('preference', 'Writing preference', 'Prefers clear, detailed step-by-step explanations.', None),
        ('project', 'Personal AI project', 'Keep project preview and production data separate.', project_map['Personal AI workspace redesign']['id']),
        ('project', 'Workspace design decision', 'Keep the existing particle sphere unchanged.', project_map['Personal AI workspace redesign']['id']),
        ('preference', 'Communication style', 'Use the name Vishnu for the project assistant.', None),
    ]
    existing_memory = memory.temporal_search(limit=500)
    for kind, subject, content, project_id in memory_examples:
        prior = next((item for item in existing_memory if str(item.get('source') or '').endswith(MARKER) and item.get('subject') == subject), None)
        expected_metadata = {'illustrative_example': True, 'dataset': MARKER, 'scope': 'project' if project_id else 'personal', **({'project_id': project_id} if project_id else {})}
        if prior:
            try:
                current_metadata = json.loads(prior.get('metadata_json') or '{}')
            except (TypeError, ValueError, json.JSONDecodeError):
                current_metadata = {}
            if current_metadata != expected_metadata:
                memory.update_memory(prior['id'], metadata=expected_metadata)
            continue
        candidate = MemoryCandidate(type=kind, subject=subject, content=content,
                                    source=f'owner-import:{MARKER}', verified=True, confidence=1.0,
                                    tags=['illustrative-example', MARKER], importance=0.6,
                                    metadata=expected_metadata)
        created['memories'].append(brain.remember(candidate))
        existing_memory.append({'source': f'owner-import:{MARKER}', 'subject': subject})

    collections = {row['title']: row for row in knowledge.collections()}
    for title in ('Personal AI project', 'Personal'):
        if title not in collections:
            collection = knowledge.create_collection(title, 'Illustrative example collection.')
            collections[title] = collection
            created['collections'].append(collection['id'])

    for title, text, category in [
        ('Personal AI Product Brief.pdf', 'Illustrative example brief for the Personal AI workspace. This is sample text for understanding the Knowledge page and is not a real PDF attachment.', 'document'),
        ('Writing and response preferences', 'Example note: keep responses clear, detailed, and step by step.', 'note'),
    ]:
        prior = next((item for item in knowledge.list(limit=500) if item.get('title') == title and item.get('source') == MARKER), None)
        expected_filename = title.rsplit('.', 1)[0] + ('.pdf' if category == 'document' else '.txt')
        if prior and prior.get('filename') == expected_filename:
            continue
        if prior:
            knowledge.delete(prior['id'])
        suffix = '.pdf' if category == 'document' else '.txt'
        content = sample_pdf(text) if category == 'document' else text.encode()
        item = knowledge.ingest(filename=expected_filename, title=title,
                                data=content, media_type='application/pdf' if suffix == '.pdf' else 'text/plain',
                                source=MARKER, access_class='owner',
                                metadata={'dataset': MARKER, 'illustrative_example': True,
                                          'knowledge_kind': category, 'available_to_vishnu': True,
                                          'collection_id': collections['Personal AI project']['id']})
        created['knowledge'].append(item['id'])


    return {'data_dir': str(data_dir), 'timezone': timezone_name, 'marker': MARKER,
            'created': {key: len(value) for key, value in created.items()}, 'ids': created,
            'existing_project_ids': sorted(marker_project_ids)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=settings.data_dir,
                        help='Existing app data directory (default: PERSONAL_AI_DATA_DIR)')
    parser.add_argument('--timezone', default='UTC', help='Timezone for Today sample times')
    parser.add_argument('--apply', action='store_true', help='Persist the labeled reference examples')
    args = parser.parse_args()
    if not args.apply:
        parser.error('No data changed. Pass --apply to write the reference examples into canonical app stores.')
    print(json.dumps(seed(args.data_dir, args.timezone), indent=2))


if __name__ == '__main__':
    main()
