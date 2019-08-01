import isodate
import json
import re
import requests


verbs = []
with open('verbs.txt', 'r') as f:
    verbs = f.readlines()
    verbs = set([verb.strip() for verb in verbs])


def parse_ingredients(text):
    results = []
    for token in text.split('\n'):
        verb = None
        if token.startswith(','):
            for verb in verbs:
                verb_phrase = ', for {}'.format(verb)
                if verb_phrase in token:
                    token = token.replace(verb_phrase, '')
                    break
        results.append({'ingredient': token, 'verb': verb})
    return results


def parse_doc(doc):
    title = doc.pop('name')
    src = doc.pop('url')
    ingredients = doc.pop('ingredients')
    image = doc.pop('image', None)
    servings = doc.pop('recipeYield', 1)
    time = doc.pop('cookTime', None)

    if image and 'static.thepioneerwoman.com' in image:
        image = image.replace(
            'static.thepioneerwoman.com/cooking/files',
            'www.thepioneerwoman.com/wp-content/uploads'
        )

    if time:
        time = isodate.parse_duration(time)
        time = int(time.total_seconds() / 60)

    if image and not image.startswith('http'):
        domain = '/'.join(src.split('/')[0:3])
        image = domain + image

    servings = str(servings)
    m = re.search('^(\d+)', servings)
    if m:
        servings = m.group(0)
    try:
        servings = int(servings)
    except ValueError:
        servings = 1

    ingredients = parse_ingredients(ingredients)

    return {
        'title': title,
        'src': src,
        'ingredients': ingredients,
        'image': image,
        'servings': servings,
        'time': time,
    }


with open('recipes.json', 'r') as f:
    for line in f:
        doc = json.loads(line)
        doc = parse_doc(doc)
        if not doc:
            continue

        ingest_uri = 'http://localhost:8080/api/recipes/ingest'
        try:
            requests.post(url=ingest_uri, json=doc)
            print('* Ingested {}'.format(doc['title']))
        except Exception:
            pass
