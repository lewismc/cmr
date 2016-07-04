import socket
import xml.etree.ElementTree as ET
import json
import sys
from Result import *
from xmlParser import XmlListConfig
import os


req_version = (3, 0)

cur_version = sys.version_info

if cur_version >= req_version:
    from configparser import ConfigParser

else:
    from ConfigParser import ConfigParser


class CMR():
    def __init__(self, configFilePath):
        """

        :param configFilePath: It is the config file containing the credentials to make CRUD requests to CMR (extention .cfg)
               Please make sure that this process can read and write to the file (changing the Token key)
        """

        if not os.access(configFilePath,
                         os.R_OK | os.W_OK):  # check if the config file has read and write permissions set
            print("[CONFIGFILE ERROR] the config file can't be open for reading/writing ")
            exit(0)

        self.config = ConfigParser()
        self.config.read(configFilePath)
        self.configFilePath = configFilePath

        self._granuleUrl = self.config.get("search", "GRANULE_URL")
        self._granuleMetaUrl = self.config.get("search", "granule_meta_url")
        self._collectionUrl = self.config.get("search", "collection_url")
        self._collectionMetaUrl = self.config.get("search", "collection_meta_url")

        self._INGEST_URL = self.config.get("ingest", "ingest_url")  # Base URL for ingesting to CMR
        self._INGEST_VALIDATION_URL = self.config.get("ingest",
                                                 "ingest_validation_url")  # Base URL to validate the ingestion

        self._CONTENT_TYPE = self.config.get("ingest", "content_type")

        self._PROVIDER = self.config.get("credentials", "provider")
        self._USERNAME = self.config.get("credentials", "username")
        self._PASSWORD = self.config.get("credentials", "password")
        self._CLIENT_ID = self.config.get("credentials", "client_id")

        self._headers_client = {"Client-Id": "servir"}
        self._REQUEST_TOKEN_URL=self.config.get("request", "request_token_url")
        self._GET_COLL_SN= self.config.get("search", "collection_by_shortname")
        self._GET_GRA_UR=self.config.get("search", "granule_by_ur")


        try:
            self._ECHO_TOKEN = self.config.get("ingest", "echo_token")  # Get the token
        except:
            self.config.set('ingest', 'ECHO_TOKEN', self._getEchoToken(self._PASSWORD))
            self.config.write(open(self.configFilePath, 'w'))
            print("Done!")
            self._ECHO_TOKEN = self.config.get("ingest", "echo_token")  # Get the token

        self._headers = {'Content-type': self._CONTENT_TYPE,
                         'Echo-Token': self._ECHO_TOKEN}

    def printHello(self):
        """
        A test function
        :return:
        """

        print ("Hello World!")

    def _searchResult(self, url, limit, **kwargs):
        """
        Search using the CMR apis
        :param url:
        :param limit:
        :param args:
        :param kwargs:
        :return: generator of xml strings
        """
        # Format the url with customized parameters
        for k, v in kwargs.items():
            url += "&{}={}".format(k, v)
        result = [requests.get(url.format(pagenum), headers=self._headers_client).content
                  for pagenum in xrange(1, (limit - 1) / 50 + 2)]
        # for res in result:
        #     for ref in re.findall("<reference>(.*?)</reference>", res):
        #         yield ref
        return [ref for res in result
                for ref in re.findall("<reference>(.*?)</reference>", res)]

    def searchGranule(self, limit=100, **kwargs):
        """
        Search the CMR granules
        :param limit: limit of the number of results
        :param kwargs: search parameters
        :return: list of results (<Instance of Result>)
        """
        print ("======== Waiting for response ========")
        metaUrl = self._granuleMetaUrl
        for k, v in kwargs.items():
            metaUrl += "&{}={}".format(k, v)

        metaResult = [requests.get(metaUrl.format(pagenum), headers=self._headers_client).content
                      for pagenum in xrange(1, (limit - 1) / 50 + 2)]

        # The first can be the error msgs
        root = ET.XML(metaResult[0])
        if root.tag == "errors":
            print (" |- Error: " + str([ch.text for ch in root._children]))
            return

        metaResult = [ref for res in metaResult
                      for ref in XmlListConfig(ET.XML(res))[2:]]

        return [Granule(m) for m in metaResult][:limit]

    def searchCollection(self, limit=100, **kwargs):
        """
        Search the CMR collections
        :param limit: limit of the number of results
        :param kwargs: search parameters
        :return: list of results (<Instance of Result>)
        """
        print ("======== Waiting for response ========")
        metaUrl = self._collectionMetaUrl
        for k, v in kwargs.items():
            metaUrl += "&{}={}".format(k, v)

        metaResult = [requests.get(metaUrl.format(pagenum), headers=self._headers_client)
                      for pagenum in xrange(1, (limit - 1) / 50 + 2)]

        try:
            metaResult = [ref for res in metaResult
                          for ref in json.loads(res.content)['feed']['entry']]
        except KeyError:
            print (" |- Error: " + str((json.loads(metaResult[0].content))["errors"]))
            return
        locationResult = self._searchResult(self._collectionUrl, limit=limit, **kwargs)
        # print locationResult

        return [Collection(m, l) for m, l in zip(metaResult, locationResult)][:limit]

    def isTokenExpired(self):
        """
        purpose: check if the token has been expired
        :return: True if the token has been expired; False otherwise.
        """
        url = self._INGEST_VALIDATION_URL + self._PROVIDER + "/collections/LarcDatasetId"
        putGranule = requests.put(url=url, headers=self._headers)
        if (len(putGranule.text.split('<error>')) > 1):  # if there is an error in the request
            temp = "Token " + self._ECHO_TOKEN + " does not exist"
            if temp == putGranule.text.split('<error>')[1].split('</error>')[
                0]:  # if the returned text from the request has the phrase token does not exist
                return True

        return False

    def _getDataSetId(self, pathToXMLFile):
        """
        Purpose : a private function to parse the xml file and returns teh dataset ID
        :param pathToXMLFile:
        :return:  the dataset id
        """
        tree = ET.parse(pathToXMLFile)
        try:
            return tree.find("DataSetId").text
        except:
            return("Could not find <DataSetId> tag")

    def _getShortName(self, pathToXMLFile):
        """
            Purpose : a private function to parse the xml file and returns teh datasetShortName
            :param pathToXMLFile:
            :return:  the datasetShortName
            """
        tree = ET.parse(pathToXMLFile)
        try:
            return tree.find("Collection").find("ShortName").text
        except:
            return("Could not find <ShortName> tag")

    def ingestCollection(self, pathToXMLFile):
        """
        :purpose : ingest the collections using cmr rest api
        :param pathToXMLFile:
        :return: the ingest collection request if it is successfully validated
        """

        data = self._getXMLData(pathToXMLFile=pathToXMLFile)
        dataset_id = self._getDataSetId(pathToXMLFile=pathToXMLFile)
        url = self._INGEST_URL + self._PROVIDER + "/collections/" + dataset_id
        validationRequest = self._validateCollection(data=data, dataset_id=dataset_id)
        if validationRequest.ok:  # if the collection is valid
            if self.isTokenExpired():  # check if the token has been expired
                self._generateNewToken()
            putCollection = requests.put(url=url, data=data, headers=self._headers)  # ingest granules

            return putCollection.content

        else:
            print(validationRequest.content)


    def updateCollection(self, pathToXMLFile):
        return self.ingestCollection(pathToXMLFile=pathToXMLFile)

    def deleteCollection(self, dataset_id):
        """
        Delete an existing colection
        :param dataset_id: the collection id
        :return: response content of the deletion request
        """

        if self.isTokenExpired():  # check if the token has been expired
            self._generateNewToken()
        url = self._INGEST_URL + self._PROVIDER + "/collections/" + dataset_id
        removeCollection=requests.delete(url, headers=self._headers)
        return removeCollection.content






    def ingestGranule(self, pathToXMLFile):
        """
        :purpose : ingest granules using cmr rest api
        :param pathToXMLFile:
        :return: the ingest granules request if it is successfully validated
        """
        url = self._INGEST_URL + self._PROVIDER + "/granules/" + self._getShortName(pathToXMLFile=pathToXMLFile)
        data = self._getXMLData(pathToXMLFile=pathToXMLFile)
        validateGranuleRequest = self._validateGranule(data=data,
                                                       datasetShortName=self._getShortName(pathToXMLFile=pathToXMLFile))
        if validateGranuleRequest.ok:
            if self.isTokenExpired():
                self._generateNewToken()
            putGranule = requests.put(url=url, data=data, headers=self._headers)

            return putGranule.content

        else:
            return (validateGranuleRequest.content)

    def _validateCollection(self, data, dataset_id):
        """
        :purpose : To validate the colection before the actual ingest
        :param data: the collection data
        :param dataset_id:
        :return: the request to validate the ingest of the collection
        """

        url = self._INGEST_URL + self._PROVIDER + "/validate/collection/" + dataset_id

        return requests.post(url=url, data=data, headers=self._headers)

    def _validateGranule(self, data, datasetShortName):
        url = self._INGEST_URL + self._PROVIDER + "/validate/granule/" + datasetShortName
        req = requests.post(url, data=data, headers=self._headers)
        return req

    def _getEchoToken(self, password):
        """
        purpose : Requesting a new token
        :param password:
        :return: the new token
        """
        top=ET.Element("token")
        username=ET.SubElement(top,"username")
        username.text=self._USERNAME
        psw=ET.SubElement(top,"password")
        psw.text=password
        client_id=ET.SubElement(top,"client_id")
        client_id.text=self._CLIENT_ID
        user_ip_address=ET.SubElement(top,"user_ip_address")
        user_ip_address.text=self._getIPAddress()
        provider=ET.SubElement(top,"provider")
        provider.text=self._PROVIDER

        data = ET.tostring(top)
        print("Requesting and setting up a new token... Please wait...")
        req = requests.post(url=self._REQUEST_TOKEN_URL, data=data,
                            headers={'Content-type': 'application/xml'})
        return req.text.split('<id>')[1].split('</id>')[0]


    def updateGranule(self, pathToXMLFile):
        return self.ingestGranule(pathToXMLFile=pathToXMLFile)



    def deleteGranule(self, granuleNative_id):
        """

        :param granuleNative_id: is typically dataset short name
        :return: the content of the deletion request
        """
        if self.isTokenExpired():
            self._generateNewToken()

        url = self._INGEST_URL + self._PROVIDER + "/granules/" + granuleNative_id
        removeGranule=requests.delete(url=url, headers=self._headers)

        return removeGranule.content





    def _getIPAddress(self):
        """
        Grep the ip address of the machine running the program
        (used to request echo token )
        :return: the address ip
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("gmail.com", 80))
        ip_address = s.getsockname()[0]
        s.close()
        return ip_address

    def _getXMLData(self, pathToXMLFile):
        data = open(pathToXMLFile).read()  # read the XML file
        return data

    def _generateNewToken(self):
        """
        replacing the old token by new one in the config file
        :return:
        """
        print("Replacing the Echo Tocken ... ")
        theNewToken= self._getEchoToken(self._PASSWORD)
        self.config.set('ingest', 'ECHO_TOKEN',theNewToken)
        self.config.write(open(self.configFilePath, 'w'))
        self._ECHO_TOKEN = theNewToken
        self._headers = {'Content-type': self._CONTENT_TYPE,
                         'Echo-Token': self._ECHO_TOKEN}

    def getCollectionByShortName(self, shortName):
        """
        verify if the ingestion was successful

        :param dataset_id:
        :return:
        """
        url = self._GET_COLL_SN+shortName
        req = requests.get(url=url)
        return req.content

    def getGranuleByUR(self,
                               granule_ur):
        """
            verify if the ingestion was successful

            :param granuleNative_id: typically the ds_short_name
            :return:
            """
        url = self._GET_GRA_UR+granule_ur
        req = requests.get(url=url)
        return req.content














