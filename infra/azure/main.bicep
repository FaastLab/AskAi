// AskAi on Azure — AKS + managed Postgres + Blob + Cache for Redis.
// Deploy: az deployment group create -g askai -f main.bicep -p main.parameters.json
//
// Pairs with the Helm chart in `infra/helm/` (set values.postgres.externalUrl,
// values.minio.endpoint, etc. to point at the resources this template creates).

param location string = resourceGroup().location
param prefix string = 'askai'

@allowed([ 'dev', 'prod' ])
param env string = 'dev'

// ---- AKS -----------------------------------------------------------------

resource aks 'Microsoft.ContainerService/managedClusters@2024-09-01' = {
  name: '${prefix}-aks-${env}'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    dnsPrefix: '${prefix}-${env}'
    agentPoolProfiles: [
      {
        name: 'system'
        count: env == 'prod' ? 3 : 2
        vmSize: env == 'prod' ? 'Standard_D4s_v5' : 'Standard_D2s_v5'
        mode: 'System'
        osType: 'Linux'
      }
    ]
    enableRBAC: true
  }
}

// ---- Postgres flexible server (with pgvector via extension) -------------

resource pg 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: '${prefix}-pg-${env}'
  location: location
  sku: { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    version: '16'
    administratorLogin: 'askai'
    administratorLoginPassword: 'PLEASE-OVERRIDE-VIA-PARAMETER-FILE'
    storage: { storageSizeGB: 64 }
  }
}

// pgvector enable
resource pgvectorExt 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: pg
  name: 'azure.extensions'
  properties: {
    value: 'VECTOR,PG_TRGM,UUID-OSSP'
    source: 'user-override'
  }
}

// ---- Cache for Redis -----------------------------------------------------

resource redis 'Microsoft.Cache/Redis@2023-08-01' = {
  name: '${prefix}-redis-${env}'
  location: location
  properties: {
    sku: { name: 'Basic', family: 'C', capacity: 0 }
  }
}

// ---- Storage account (Blob) ----------------------------------------------

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: replace('${prefix}st${env}', '-', '')
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: { allowBlobPublicAccess: false }
}

resource container 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  name: '${storage.name}/default/askai'
  properties: { publicAccess: 'None' }
}

output aksName string = aks.name
output pgFqdn string = pg.properties.fullyQualifiedDomainName
output redisHost string = redis.properties.hostName
output blobAccount string = storage.name
