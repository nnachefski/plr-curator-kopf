#!/bin/bash

# apply the CRD
oc apply -f plr-curator.crd

# deploy the operator (serviceacount, clusterrole, clusterrolebinding, secret, and deployment objects)
# note: perms (apis-to-verbs) for the operator were scoped as tightly as possible
cat plr-curator-kopf.yaml |sed "s/\$HARBOR_CFG/$HARBOR_CFG/" |oc apply -f -

#if you want to peer a locally running operator: 
# - pip-3.8 install kopf
# - apply the peering CRDs (below)
# - apply the included ClusterKopfPeering yaml
# - run 'kopf run -A handlers.py --priority=100'"

# https://raw.githubusercontent.com/zalando-incubator/kopf/master/peering.yaml

