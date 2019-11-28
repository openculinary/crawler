# RecipeRadar Crawler

The RecipeRadar crawler provides an abstraction layer over external recipe websites, returning data in a format which can be ingested into the RecipeRadar search engine.

Much of this is possible thanks to the open source [recipe-scrapers](https://pypi.org/project/recipe-scrapers) library; any improvements, fixes, and site coverage added there will benefit the crawler service.

In addition, scripts are provided to crawl from two readily-available sources of recipe URLs:

* `openrecipes` - a set of ~175k public recipe URLs
* `reciperadar` - the set of recipe URLs already known to RecipeRadar

The `reciperadar` set is useful during changes to the crawling and indexing components of the RecipeRadar application itself; it provides a quick way to recrawl and reindex existing recipes.

Outbound requests are routed via [squid](https://www.squid-cache.org) to avoid burdening origin recipe sites with repeated content retrieval requests.

## Install dependencies

Make sure to follow the RecipeRadar [infrastructure](https://www.github.com/openculinary/infrastructure) setup to ensure all cluster dependencies are available in your environment.

## Development

To install development tools and run linting and tests locally, execute the following commands:

```
pipenv install --dev
pipenv run make
```

## Local Deployment

To deploy the service to the local infrastructure environment, execute the following commands:

```
sudo sh -x ./build.sh
sh -x ./deploy.sh
```

## Operations

### Initial data load

To crawl and index `openrecipes` from scrath, execute the following commands:

```
cd openrecipes
pipenv install
pipenv run python crawl.py
```

NB: This requires you to download the [openrecipes](https://github.com/fictivekin/openrecipes) dataset and extract it to a file named 'recipes.json'

### Recrawling and reindexing

To recrawl and reindex the entire known `reciperadar` recipe set, execute the following commands:

```
cd reciperadar
pipenv install
pipenv run python crawl_urls.py --recrawl
```

To reindex `reciperadar` recipes containing products named `tofu`, execute the following command:

```
cd reciperadar
pipenv install
pipenv run python recipes.py --reindex --where "exists (select * from recipe_ingredients as ri join ingredient_products as ip on ip.ingredient_id = ri.id where ri.recipe_id = recipes.id and ip.product = 'tofu')"
```

NB: Running either of these commands without the `--reindex` / `--recrawl` argument will run in a 'safe mode' and tell you about the entities which match your query, without performing any actions on them.

### Proxy selection

Sometimes individual websites may block or rate-limit the crawler; it's best to avoid making too many requests to an individual website, and to be as respectful as possible of their operational and network costs.

Sometimes it can be worth temporarily switching the crawler to use an anonymized proxy service.  Until this is available as a configuration setting, this can be done by updating the crawler application code and redeploying the service.
