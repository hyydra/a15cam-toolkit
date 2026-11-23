# Builds the A15Cam APK without Gradle (aapt2 + javac + d8 + apksigner). Needs ANDROID_SDK_ROOT (build-tools 36.0.0, platform android-35) and JAVA_HOME (JDK 17). Run: powershell -File build.ps1
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$sdk  = $env:ANDROID_SDK_ROOT
$bt   = "$sdk\build-tools\36.0.0"
$jar  = "$sdk\platforms\android-35\android.jar"
$jdk  = $env:JAVA_HOME
$out  = "$root\out"
Remove-Item $out -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force "$out\classes", "$out\dex" | Out-Null

& "$bt\aapt2.exe" link -o "$out\base.apk" -I $jar --manifest "$root\AndroidManifest.xml" --min-sdk-version 28 --target-sdk-version 34
& "$jdk\bin\javac.exe" -source 8 -target 8 -Xlint:-options -classpath $jar -d "$out\classes" "$root\src\com\claude\a15cam\ShotActivity.java"
$cls = Get-ChildItem "$out\classes" -Recurse -Filter *.class | ForEach-Object { $_.FullName }
& "$bt\d8.bat" --lib $jar --min-api 28 --output "$out\dex" @cls
& "$jdk\bin\jar.exe" --help *> $null
# classes.dex hozzaadasa az apk-hoz (a zip-be ures nev nelkul, a gyokerbe)
Push-Location "$out\dex"
& "$jdk\bin\jar.exe" uf "$out\base.apk" classes.dex
Pop-Location
$ks = "$root\debug.keystore"
if (-not (Test-Path $ks)) {
    & "$jdk\bin\keytool.exe" -genkeypair -keystore $ks -storepass android -keypass android -alias a15cam -keyalg RSA -keysize 2048 -validity 10000 -dname 'CN=A15Cam' | Out-Null
}
& "$bt\zipalign.exe" -f -p 4 "$out\base.apk" "$out\aligned.apk"
& "$bt\apksigner.bat" sign --ks $ks --ks-pass pass:android --key-pass pass:android --out "$out\A15Cam.apk" "$out\aligned.apk"
Get-Item "$out\A15Cam.apk" | Select-Object FullName, Length
