import kopf
import kubernetes
import datetime
import operator
import re
from openshift.dynamic import DynamicClient

#
# Re-usable funtions
#

# parse PipelineRunCurator CustomResource objects data and sanity check
def parse_plrc_data(cr, logger):
    try:
        ns = cr.spec['namespace']
    except:
        logger.error("- couldnt parse 'Namespace' from the PipelineRunCurator CustomResource, failing...")
        return

    try:
        limit = cr.spec['plrlimit']
    except:
        logger.error("- couldnt parse 'PLRLimit' from the PipelineRunCurator CustomResource, failing...")
        return

    try:
        repoNameParam = cr.spec['repoparam']
    except:
        logger.error("- couldnt parse 'RepoParam' from the PipelineRunCurator CustomResource, failing...")
        return

    return {'namespace': ns,
            'limit': limit,
            'repoNameParam': repoNameParam
            }


#
# Event Handlers
#

# this event handler processes ALL PipeLineRunCurator CRs on startup
@kopf.on.resume('nicknach.net', 'v1', 'plrcurators')
def curator_handler_onresume(spec, meta, logger, **_):
    # initialize the kube and openshift clients
    k8s_client = kubernetes.client.ApiClient()
    dyn_client = DynamicClient(k8s_client)

    # get PLRCs in the operator's namespace.  We only care about PLRCs in the operator's namespace, all others are ignored.
    cr_resources = dyn_client.resources.get(api_version='nicknach.net/v1', kind='PLRCurator')
    crs = cr_resources.get(namespace=meta.get('namespace'))

    # do some sanity checking on resume
    # 1. make sure each PLRC has the required data, if not, log it.
    # 2. make sure each PLRC has only one instance per namespace.  if not, log it.

    PLRCS_NS = set()
    for cr in crs.items:
        # get the data for this PLRC instance, pass PLCR object and the logger
        plrc_data = parse_plrc_data(cr, logger)

        # if not able to parse PLRC data, fail (continue).  Reason was logged already in parse_plrc_data
        if not plrc_data:
            continue

        if plrc_data['namespace'] in PLRCS_NS:
            logger.error("- ERROR: there is more than one PipelineRunCurator configured for namespace '%s'"%(spec['namespace']))
        else:
            PLRCS_NS.add(plrc_data['namespace'])


# this event handler processes NEW PipeLineRunCurator CRs on creation
@kopf.on.create('nicknach.net', 'v1', 'plrcurators')
def curator_handler_oncreate(spec, meta, logger, **_):
    logger.info("- processing PipelineRunCurator '%s' on 'create'..."%(meta.get('name')))

    # initialize the kube and openshift clients
    k8s_client = kubernetes.client.ApiClient()
    dyn_client = DynamicClient(k8s_client)

    # get PLRCs in the operator's namespace.  We only care about PLRCs in the operator's namespace, all others are ignored.
    cr_resources = dyn_client.resources.get(api_version='nicknach.net/v1', kind='PLRCurator')
    crs = cr_resources.get(namespace=meta.get('namespace'))

    for cr in crs.items:
        if cr['metadata']['name'] == meta['name']:
            # we have found the PLRC which created this event, ignore
            continue

        # now check each exsiting PLRC to see if a duplicate is being created.
        if cr.spec['namespace'] == spec['namespace']:

            logger.info("- only one PipelineRunCurator object is needed for namespace '%s', deleting '%s'"%(spec['namespace'], meta.get('name')))
            try:
                cr_resources.delete(name=meta.get('name'), namespace=spec['namespace'])
            except:
                logger.error("- could not delete PipelineRunCurator '%s' in namespace '%s'"%(meta.get('name'), spec['namespace']))
            else:
                logger.info("- successfully deleted PipelineRunCurator '%s'"%(meta.get('name')))


# this event handler handles events on-resume and on-create for PipelineRun objects
@kopf.on.resume('tekton.dev', 'v1beta1', 'pipelineruns')
@kopf.on.create('tekton.dev', 'v1beta1', 'pipelineruns')
def plr_handler(spec, meta, logger, **_):
    # initialize the kube and openshift clients
    k8s_client = kubernetes.client.ApiClient()
    dyn_client = DynamicClient(k8s_client)

    # get PLRCs in the operator's namespace.  We only care about PLRCs in the operator's namespace, all others are ignored.
    # this will be used later to apply PLRLIMITs and Namespace
    cr_resources = dyn_client.resources.get(api_version='nicknach.net/v1', kind='PLRCurator')
    crs = cr_resources.get(namespace=meta.get('namespace'))

    # get all PipelineRun objects
    plr_resources = dyn_client.resources.get(api_version='tekton.dev/v1beta1', kind='PipelineRun')

    # check to see if this is a PLR that we should be curating (check it's namespace with the namespaces of the PLRCs)
    isValid = False
    for cr in crs.items:
        if meta.get('namespace') == cr.spec['namespace']:
            isValid = True
            break

    if isValid:
        logger.info("- processing PipelineRun '%s' ..."%(meta.get('name')))
    else:
        logger.info("- skipping PipelineRun '%s', no PipelineRunCurator is defined for namespace '%s'"%(meta.get('name'), meta.get('namespace')))

    # iterate over our PipelineRun Curator configs (PLRCs)
    for cr in crs.items:
        # get the data for this PLRC instance, pass PLCR object and the logger
        plrc_data = parse_plrc_data(cr, logger)
        
        # if not able to parse PLRC data, fail (continue).  Reason was logged already in parse_plrc_data
        if not plrc_data:
            continue

        # filter by the namespace configured in the PLRC
        plrs = plr_resources.get(namespace=plrc_data['namespace'])

        # python dict to store PLRs
        pipelineruns = {}

        # iterate over all PLRs in the designated namespace for this PLRC (namespace filter above on the 'get')
        for plr in plrs.items:
            # there is a many-to-one mapping between repo's sending hooks to an EventListener (and Pipeline)
            # Pipeline's are configured by "type"  Ex: container-build-push-from-source or gradle-build-push-with-helm

            # because we want to curate by repo name and not pipeline name/type, we need the PLRC CustomResource to provide parameter that is used for the repo's name
            # grab the repo's name from the PipeLineRun object using repoNameParam
            repoName = None
            for item in plr.spec.params:
                if item['name'] == plrc_data['repoNameParam']:
                    repoName = item['value']

            # if not able to parse the repo name, fail with message
            if not repoName:
                logger.error("- couldnt parse repo name from PipelineRun '%s' in namespace '%s' using param '%s', skipping... "%(plr.metadata.name, plr.metadata.namespace, plrc_data['repoNameParam']))
                continue
            else:
                # debug log on success
                logger.debug("- found the repo name '%s' for PipelineRun '%s' using param '%s'"%(repoName, plr.metadata.name, plrc_data['repoNameParam']))

            # a new dict item to store info about this specific PLR
            new = {
                'name': plr.metadata.name,
                'namespace': plr.metadata.namespace,
                'created': datetime.datetime.fromisoformat(plr.metadata.creationTimestamp.strip('Z')),
                }

            # try to append this PLR data to the main PLRs dict using the repo's name as the key
            try:
                pipelineruns[repoName].append(new)
            except:
                # if that failed, then we havent seen this repo before... add it
                pipelineruns[repoName] = [new]

        # iterate over PLRs for each repo
        for name, item in pipelineruns.items():
            # sort by "Created" datetime
            sortedList = sorted(item, key=operator.itemgetter('created'), reverse=True)

            # if the number of PLRs for this repo is less-than-or-equal-to the limit, nothing to do here
            if len(sortedList) <= plrc_data['limit']:
                continue

            # if it got this far, something needs curating
            logger.info("- processing PipelineRun curation for repo '%s'.  There are '%s' PipelineRuns and the limit is '%s'"%(name, len(sortedList), plrc_data['limit']))

            # iterate over the sorted PLRs for this repo, starting at the PLRLIMIT
            # (ie, delete every PLR for this repo that is greater than the limit)
            for line in sortedList[plrc_data['limit']:]:
                # check sanity of data by making sure PLR name and namespace exists, print message
                if 'name' and 'namespace' in line:
                    logger.info("- deleting PLR '%s' in namespace '%s'"%(line['name'], line['namespace']))

                    # delete the offending PLR and log the result
                    try:
                        plr_resources.delete(name=line['name'], namespace=line['namespace'])
                    except:
                        logger.error("- failed to delete PipelineRun '%s' in namespace '%s'"%(line['name'], line['namespace']))
                    else:
                        logger.info("- successfully deleted PipelineRun '%s' in namespace '%s'"%(line['name'], line['namespace']))
