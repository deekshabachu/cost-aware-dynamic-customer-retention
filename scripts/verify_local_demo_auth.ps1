$ErrorActionPreference = 'Stop'
$apiBase = 'http://127.0.0.1:5173/api'

function Convert-SecureStringToPlainText([System.Security.SecureString] $Value) {
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}

function Get-FailureStatus([scriptblock] $Request) {
    try {
        $null = & $Request
        return 200
    } catch {
        if ($_.Exception.Response) { return [int]$_.Exception.Response.StatusCode }
        throw 'The local API request failed before receiving an HTTP response.'
    }
}

function Get-LoginSession([string] $Email, [string] $Password, [bool] $Admin) {
    $path = if ($Admin) { '/admin/auth/login' } else { '/auth/login' }
    $minimumLength = 4
    if ($Password.Length -lt $minimumLength -or $Password.Length -gt 128) {
        throw "The entered password length is outside the API limit ($minimumLength to 128 characters). No request was sent and no password was displayed."
    }
    $json = @{ email = $Email; password = $Password } | ConvertTo-Json -Compress
    try {
        return Invoke-RestMethod -UseBasicParsing -Method Post -Uri ($apiBase + $path) `
            -ContentType 'application/json' -Body $json -TimeoutSec 10
    } catch {
        $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
        $safeValidation = @()
        if ($status -eq 422 -and $_.ErrorDetails.Message) {
            try {
                $errorBody = $_.ErrorDetails.Message | ConvertFrom-Json
                foreach ($item in $errorBody.detail) {
                    # Never display the response's `input` field: it may contain the password.
                    $location = @($item.loc | ForEach-Object { [string]$_ }) -join '.'
                    $message = [string]$item.msg
                    if ($location -match '^[A-Za-z0-9_.-]+$' -and $message -notmatch '[\r\n]') {
                        $safeValidation += "field=$location; reason=$message"
                    }
                }
            } catch {
                $safeValidation = @()
            }
        }
        $diagnostic = if ($safeValidation.Count) { ' Validation: ' + ($safeValidation -join '; ') } else { '' }
        throw "Login for $Email failed (HTTP $status).$diagnostic No credential or token was displayed."
    }
}

$health = Invoke-RestMethod -UseBasicParsing -Uri ($apiBase + '/health') -TimeoutSec 5
if ($health.status -ne 'healthy') { throw 'Backend health check failed through the Vite proxy.' }
'vite_proxy_health=PASS'

$adminSecure = Read-Host 'Enter the existing administrator password' -AsSecureString
$adminPassword = Convert-SecureStringToPlainText $adminSecure
$adminSession = Get-LoginSession 'admin@littleleaf.local' $adminPassword $true
$adminPassword = $null
$adminSecure = $null
$adminHeaders = @{ Authorization = 'Bearer ' + $adminSession.access_token }
$null = Invoke-RestMethod -UseBasicParsing -Uri ($apiBase + '/admin/dashboard') -Headers $adminHeaders -TimeoutSec 10
'admin_login_and_dashboard=PASS'
$wrongStatus = Get-FailureStatus { Invoke-RestMethod -UseBasicParsing -Method Post `
    -Uri ($apiBase + '/admin/auth/login') -ContentType 'application/json' `
    -Body (@{ email = 'admin@littleleaf.local'; password = 'Definitely-Wrong-Demo-Password!' } | ConvertTo-Json -Compress) -TimeoutSec 10 }
if ($wrongStatus -ne 401) { throw "Incorrect administrator password returned HTTP $wrongStatus instead of 401." }
'admin_wrong_password_rejected=PASS'
$ordersAsAdmin = Get-FailureStatus { Invoke-RestMethod -UseBasicParsing -Uri ($apiBase + '/orders') -Headers $adminHeaders -TimeoutSec 10 }
if ($ordersAsAdmin -ne 401) { throw "Administrator token unexpectedly accessed customer orders (HTTP $ordersAsAdmin)." }
'admin_cannot_use_customer_order_route=PASS'

$customerChecks = @(
    @{ Email = 'customer01@demo.customer-retention.local'; ExpectedOffer = $false; Label = 'customer01' },
    @{ Email = 'customer02@demo.customer-retention.local'; ExpectedOffer = $true; Label = 'customer02' }
)
foreach ($customer in $customerChecks) {
    $secure = Read-Host "Enter the existing $($customer.Label) password" -AsSecureString
    $password = Convert-SecureStringToPlainText $secure
    $session = Get-LoginSession $customer.Email $password $false
    $password = $null
    $secure = $null
    $headers = @{ Authorization = 'Bearer ' + $session.access_token }

    $orders = Invoke-RestMethod -UseBasicParsing -Uri ($apiBase + '/orders') -Headers $headers -TimeoutSec 10
    $offer = Invoke-RestMethod -UseBasicParsing -Uri ($apiBase + '/retention/offer') -Headers $headers -TimeoutSec 10
    if ([bool]$offer.assigned -ne $customer.ExpectedOffer) {
        throw "$($customer.Label) has an unexpected assigned-offer state. No records were changed."
    }
    $adminAccess = Get-FailureStatus { Invoke-RestMethod -UseBasicParsing -Uri ($apiBase + '/admin/dashboard') -Headers $headers -TimeoutSec 10 }
    if ($adminAccess -ne 401) { throw "$($customer.Label) unexpectedly accessed an admin route (HTTP $adminAccess)." }
    "$($customer.Label)_login=PASS order_count=$(@($orders).Count) offer_assignment_correct=True admin_access_blocked=True"
    $session = $null
    $headers = $null
    $orders = $null
    $offer = $null
}

$adminSession = $null
$adminHeaders = $null
'All local demo authentication checks passed. No credentials or tokens were printed.'
